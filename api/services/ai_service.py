import os
import re
import json
import logging
import threading
from typing import Optional, Any
from openai import OpenAI

from api.config import settings

logger = logging.getLogger("ai_service")

_token_usage_lock = threading.Lock()
_accumulated_token_usage: list = []


def get_and_reset_token_usage() -> list:
    with _token_usage_lock:
        result = list(_accumulated_token_usage)
        _accumulated_token_usage.clear()
        return result


def _build_directory_context(filepath: str) -> str:
    dir_path = os.path.dirname(os.path.normpath(filepath))
    parts = []
    current = dir_path
    for _ in range(3):
        parent = os.path.dirname(current)
        name = os.path.basename(current)
        parent_name = os.path.basename(parent)
        if not name or name == parent_name or not parent_name:
            break
        parts.append(name)
        current = parent
    parts.reverse()
    return " / ".join(parts) if parts else os.path.basename(dir_path)


def _extract_text_from_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            text = _extract_text_from_content(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "value", "reasoning", "reasoning_content"):
            text = _extract_text_from_content(value.get(key))
            if text:
                return text
        return ""
    return ""


def _call_ai_api(prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
    api_key = settings.ai_api_key
    base_url = settings.ai_base_url.rstrip("/")
    model = settings.ai_model
    max_tokens = settings.ai_max_tokens
    if not api_key:
        return None

    if not system_prompt:
        system_prompt = "You are a media recognition assistant. Identify the movie or TV series name from the file path."

    logger.info("AI API请求: url=%s, model=%s, max_tokens=%s", base_url, model, max_tokens)

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)

        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }

        if "deepseek" in model.lower():
            kwargs["reasoning_effort"] = "low"

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if any(marker in error_str for marker in ("reasoning", "thinking", "think")):
                logger.info("API不支持reasoning参数，正在重试...")
                kwargs.pop("reasoning_effort", None)
                response = client.chat.completions.create(**kwargs)
            else:
                raise

        message = response.choices[0].message

        reasoning_val = getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)
        if reasoning_val:
            reasoning_text = _extract_text_from_content(reasoning_val)
            if reasoning_text:
                logger.info("AI思考过程: %s", reasoning_text[:2000])

        raw = ""
        content_val = getattr(message, "content", None)
        if content_val is not None:
            raw = _extract_text_from_content(content_val)

        if not raw:
            for key in ("reasoning_content", "reasoning"):
                val = getattr(message, key, None)
                if val:
                    raw = _extract_text_from_content(val)
                    if raw:
                        break

        usage = response.usage
        if usage:
            logger.info(
                "AI API token用量: input=%s, output=%s, 总计=%s (上限=%s)",
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens,
                max_tokens,
            )
            with _token_usage_lock:
                _accumulated_token_usage.append({
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                })

        logger.debug("AI API原始响应: %s", raw)

        content = raw.strip()
        content = re.sub(r'^["\'"\']+', "", content)
        content = re.sub(r'["\'"\']+$', "", content)
        content = content.strip()

        if content and len(content) >= 2:
            return content
        logger.warning("AI API返回内容无效: raw=%r", raw)
    except Exception as e:
        logger.error("AI API调用失败: %s", str(e))
    return None


def infer_title_from_directory(filepath: str) -> Optional[str]:
    directory_context = _build_directory_context(filepath)
    filename = os.path.basename(filepath)
    logger.info("AI推断剧名: filepath=%s, dir_context=%s", filepath, directory_context)

    prompt = (
        "Identify the TV series or movie name from the given file directory path and filename.\n"
        "Rules:\n"
        "1. If the file is a TV episode, output ONLY the series name (NOT the episode title)\n"
        "2. If the file is a movie, output the movie name\n"
        "3. Output ONLY the name, no explanation, no quotes, no punctuation\n"
        "4. Output in the original language (Chinese name in Chinese, English name in English)\n\n"
        f"Directory: {directory_context}\n"
        f"Filename: {filename}\n\n"
        "Answer:"
    )

    result = _call_ai_api(prompt)
    if result:
        logger.info("AI推断结果: %s", result)
    else:
        logger.warning("AI推断无结果")
    return result


def parse_media_filename(filename: str, directory: Optional[str] = None) -> Optional[dict]:
    api_key = settings.ai_api_key
    if not api_key:
        return None

    dir_context = ""
    if directory:
        dir_context = _build_directory_context(directory)

    logger.info("AI解析文件名: filename=%s, dir_context=%s", filename, dir_context)

    system_prompt = "You are a strict media filename parser. Output ONLY valid JSON, no explanations, no markdown, no code blocks."

    if dir_context:
        prompt = (
            'From the filename and directory path below, extract the media metadata as JSON.\n'
            'Rules:\n'
            '1. title: the real series/movie name. If filename has both Chinese and English, prefer English.\n'
            '2. year: 4-digit year if present, otherwise null.\n'
            '3. season: default 1 if not specified. Look for S01, S1, Season 1, 第2季, etc.\n'
            '4. episode: episode number if present, otherwise null. Look for E05, EP5, [01], 第5话, etc.\n'
            '5. Ignore resolution (1080p, 4K), codec (x264, HEVC), source (WEB-DL, BluRay), group tags [KTXP], language tags (CHS, CHT).\n'
            '6. Use the directory context to determine the correct series name when filename only contains episode info.\n'
            'Output format: {"title": "...", "year": null, "season": 1, "episode": null}\n\n'
            f'Directory: {dir_context}\n'
            f'Filename: {filename}\n\n'
            'JSON:'
        )
    else:
        prompt = (
            'From the filename below, extract the media metadata as JSON.\n'
            'Rules:\n'
            '1. title: the real series/movie name. If filename has both Chinese and English, prefer English.\n'
            '2. year: 4-digit year if present, otherwise null.\n'
            '3. season: default 1 if not specified. Look for S01, S1, Season 1, 第2季, etc.\n'
            '4. episode: episode number if present, otherwise null. Look for E05, EP5, [01], 第5话, etc.\n'
            '5. Ignore resolution (1080p, 4K), codec (x264, HEVC), source (WEB-DL, BluRay), group tags [KTXP], language tags (CHS, CHT).\n'
            'Output format: {"title": "...", "year": null, "season": 1, "episode": null}\n\n'
            f'Filename: {filename}\n\n'
            'JSON:'
        )

    result = _call_ai_api(prompt, system_prompt=system_prompt)
    if not result:
        return None

    try:
        cleaned = re.sub(
            r'^```(?:json)?\s*|\s*```$', "", result, flags=re.IGNORECASE
        )
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            logger.warning("AI返回非对象JSON: %s", result[:200])
            return None

        title = data.get("title", "").strip()
        if not title or len(title) < 2:
            logger.warning("AI解析title无效: %s", result[:200])
            return None

        year = data.get("year")
        if year is not None and not isinstance(year, (int, str)):
            year = None
        if isinstance(year, str):
            year_text = year.strip()
            year = int(year_text) if year_text.isdigit() else None

        try:
            season = int(data.get("season", 1))
        except (TypeError, ValueError):
            season = 1

        episode_raw = data.get("episode")
        episode = None
        if episode_raw is not None:
            try:
                episode = int(episode_raw)
            except (TypeError, ValueError):
                episode = None

        parsed = {
            "title": title,
            "year": year,
            "season": season,
            "episode": episode,
        }
        logger.info("AI解析结果: %s", parsed)
        return parsed

    except json.JSONDecodeError as e:
        logger.warning("AI JSON解析失败: %s, 内容: %s", e, result[:300])
        return None