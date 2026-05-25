import os
import re
import asyncio
import logging
from typing import Optional, List
from guessit import guessit

logger = logging.getLogger("recognition_service")

from utils.helpers import (
    clean_search_title,
    derive_title_from_filename,
    extract_episode_number,
    safe_int,
    candidate_to_result,
)
from db.tmdb_api import (
    fetch_tmdb_candidates_async,
    fetch_bgm_candidates,
    fetch_tmdb_episode_meta_async,
    fetch_hybrid_episode_meta,
    fetch_tmdb_credits_async,
)
from api.config import settings
from api.schemas.media import (
    MediaFileParseResponse,
    MediaRecognitionResponse,
    EpisodeMetadata,
)
from api.services.ai_service import infer_title_from_directory, parse_media_filename

_ai_result_cache: dict = {}


async def prepopulate_ai_cache(files: list) -> None:
    """预填充 AI 结果缓存：对每个唯一的 group_id 调用一次 AI。"""
    unique_groups = {}
    for f in files:
        gid = getattr(f, "group_id", None) or (f.get("group_id") if isinstance(f, dict) else None)
        fp = getattr(f, "filepath", None) or getattr(f, "path", None) or (f.get("filepath") or f.get("path") if isinstance(f, dict) else None)
        fn = getattr(f, "filename", None) or (f.get("filename") if isinstance(f, dict) else None) or getattr(f, "name", None) or (f.get("name") if isinstance(f, dict) else None)
        if gid and gid not in _ai_result_cache and gid not in unique_groups and fp:
            unique_groups[gid] = (fn, fp)

    if not unique_groups:
        return

    for gid, (fn, fp) in unique_groups.items():
        try:
            pure_name, _ = os.path.splitext(fn or "unknown.mkv")
            result = await asyncio.to_thread(parse_media_filename, f"{pure_name}.mkv", fp)
            if result and result.get("title"):
                _ai_result_cache[gid] = result["title"]
                logger.info("预填充AI缓存: group_id=%s, title=%s", gid, result["title"])
        except Exception as e:
            logger.warning("预填充AI缓存失败: group_id=%s, error=%s", gid, e)


class RecognitionService:
    @staticmethod
    def parse_filename(filename: str) -> MediaFileParseResponse:
        pure_name, ext = os.path.splitext(filename)
        guess_data = guessit(pure_name)
        title = guess_data.get("title", derive_title_from_filename(pure_name))
        year = guess_data.get("year")
        season = guess_data.get("season", 1)
        episode = extract_episode_number(pure_name, guess_data)
        logger.info("解析文件名: filename=%s, title=%s, year=%s, season=%s, episode=%s",
                     filename, title, year, season, episode)
        return MediaFileParseResponse(
            title=title,
            year=safe_int(year, None),
            season=safe_int(season, 1),
            episode=safe_int(episode, None),
            extension=ext,
            pure_name=pure_name,
        )

    @staticmethod
    def _extract_bracket_titles(pure_name: str) -> List[str]:
        titles = []
        bracket_patterns = re.findall(r"\[([^\]]+)\]", pure_name)
        for content in bracket_patterns:
            text = content.strip()
            if text:
                cleaned = clean_search_title(text)
                if cleaned and len(cleaned) >= 2:
                    titles.append(cleaned)
        return titles

    @staticmethod
    async def _build_search_queries(guess_title: str, pure_name: str, filepath: Optional[str] = None, group_id: Optional[str] = None) -> List[str]:
        queries = []

        ai_title_from_parse = None
        if filepath and settings.ai_api_key:
            if group_id and group_id in _ai_result_cache:
                ai_title_from_parse = _ai_result_cache[group_id]
                logger.info("使用缓存的AI结果: group_id=%s, title=%s", group_id, ai_title_from_parse)
            else:
                ai_result = await asyncio.to_thread(
                    parse_media_filename, f"{pure_name}.mkv", filepath
                )
                if ai_result and ai_result.get("title"):
                    ai_title_from_parse = ai_result["title"]
                    if group_id:
                        _ai_result_cache[group_id] = ai_title_from_parse
                        logger.info("AI结果已缓存: group_id=%s, title=%s", group_id, ai_title_from_parse)
        elif filepath:
            logger.warning("AI API密钥未配置，将跳过AI辅助标题推断，如需使用请在设置中配置AI API Key")

        if ai_title_from_parse:
            ai_cleaned = clean_search_title(ai_title_from_parse)
            if ai_cleaned:
                queries.append(ai_cleaned)

        primary = clean_search_title(guess_title or "")
        if primary and primary.lower() not in [q.lower() for q in queries]:
            queries.append(primary)

        bracket_titles = RecognitionService._extract_bracket_titles(pure_name)
        for bt in bracket_titles:
            if bt.lower() not in [q.lower() for q in queries]:
                queries.append(bt)

        if filepath and not ai_title_from_parse and settings.ai_api_key:
            ai_title = await asyncio.to_thread(infer_title_from_directory, filepath)
            if ai_title:
                ai_cleaned = clean_search_title(ai_title)
                if ai_cleaned and ai_cleaned.lower() not in [q.lower() for q in queries]:
                    queries.append(ai_cleaned)

        logger.info("构建搜索查询: guess_title=%s, queries=%s", guess_title, queries)
        return queries

    @staticmethod
    async def recognize_media(
        filename: str,
        filepath: Optional[str] = None,
        source: str = "tmdb",
        media_type_override: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> MediaRecognitionResponse:
        try:
            parse_result = RecognitionService.parse_filename(filename)

            is_tv = False
            if media_type_override == "tv":
                is_tv = True
            elif media_type_override == "movie":
                is_tv = False
            else:
                is_tv = (
                    parse_result.season is not None
                    and parse_result.season > 0
                    and parse_result.episode is not None
                )

            logger.info("开始识别: filename=%s, filepath=%s, source=%s, is_tv=%s",
                         filename, filepath, source, is_tv)

            candidates = []
            match_result = None
            status_msg = "未识别"

            if source == "tmdb" and not settings.tmdb_api_key:
                status_msg = "未配置 TMDb API 密钥"
            elif source == "bgm" and not settings.bgm_api_key:
                status_msg = "未配置 BGM API 密钥"
            else:
                queries = await RecognitionService._build_search_queries(
                    parse_result.title or "", parse_result.pure_name or "", filepath, group_id
                )

                for search_title in queries:
                    if source == "tmdb":
                        candidates = await fetch_tmdb_candidates_async(
                            search_title, parse_result.year, is_tv, settings.tmdb_api_key
                        )
                    else:
                        candidates = fetch_bgm_candidates(
                            search_title, parse_result.year, settings.bgm_api_key
                        )

                    logger.info("搜索: title=%s, candidates=%s", search_title, len(candidates) if candidates else 0)

                    if candidates:
                        if source == "tmdb":
                            match_result = candidate_to_result(candidates[0], "TMDb命中")
                        else:
                            match_result = candidate_to_result(candidates[0], "BGM命中")
                        if match_result and len(match_result) >= 4:
                            _, mid, _, _ = match_result
                            if mid and mid != "None":
                                break
                        match_result = None
                    else:
                        status_msg = f"尝试 '{search_title}' 未找到结果"

            metadata = None
            suggested_name = None
            recognized_title = None
            match_id = None

            if match_result and len(match_result) >= 4:
                title, mid, msg, meta = match_result
                if mid and mid != "None":
                    recognized_title = title
                    match_id = mid
                    status_msg = "识别成功"
                    logger.info("识别成功: title=%s, id=%s, is_tv=%s", title, mid, is_tv)

                    metadata = EpisodeMetadata(
                        id=mid,
                        match_id=mid,
                        provider="tmdb" if source == "tmdb" else "bgm",
                        title=title,
                        original_title=meta.get("original_title"),
                        year=safe_int(meta.get("year")),
                        overview=meta.get("overview"),
                        poster=meta.get("poster"),
                        fanart=meta.get("fanart"),
                        rating=meta.get("rating"),
                        votes=meta.get("votes"),
                        genres=meta.get("genres", []),
                        studios=meta.get("studios", []),
                        release=meta.get("release"),
                        status=meta.get("status"),
                        runtime=meta.get("runtime"),
                        season=parse_result.season,
                        episode=parse_result.episode,
                        type="episode" if is_tv else "movie",
                    )

                    # 获取演职人员信息
                    if source == "tmdb" and settings.tmdb_api_key:
                        actors, directors = await fetch_tmdb_credits_async(
                            mid, is_tv=is_tv, api_key=settings.tmdb_api_key
                        )
                        metadata.actors = actors
                        metadata.directors = directors

                    if (
                        is_tv
                        and mid != "None"
                        and parse_result.season
                        and parse_result.episode
                    ):
                        if source == "tmdb" and settings.tmdb_api_key:
                            ep_title, ep_plot, still = await fetch_tmdb_episode_meta_async(
                                mid,
                                parse_result.season,
                                parse_result.episode,
                                settings.tmdb_api_key,
                                title,
                                settings.bgm_api_key,
                            )
                            metadata.ep_title = ep_title
                            metadata.ep_plot = ep_plot
                            metadata.still = still
                        elif source == "bgm" and settings.bgm_api_key:
                            ep_title, ep_plot, still, s_poster = fetch_hybrid_episode_meta(
                                title,
                                mid,
                                parse_result.season,
                                parse_result.episode,
                                settings.bgm_api_key,
                                settings.tmdb_api_key,
                                parse_result.year,
                            )
                            metadata.ep_title = ep_title
                            metadata.ep_plot = ep_plot
                            metadata.still = still
                            metadata.s_poster = s_poster

                    if is_tv:
                        s_str = f"S{parse_result.season:02d}" if parse_result.season else ""
                        e_str = f"E{parse_result.episode:02d}" if parse_result.episode else ""
                        ep_name_str = f" - {metadata.ep_title}" if metadata.ep_title else ""
                        ext = parse_result.extension or ".mkv"
                        suggested_name = f"{title} - {s_str}{e_str}{ep_name_str}{ext}"
                    else:
                        year_str = f" ({parse_result.year})" if parse_result.year else ""
                        ext = parse_result.extension or ".mkv"
                        suggested_name = f"{title}{year_str}{ext}"

            return MediaRecognitionResponse(
                success=metadata is not None,
                original_filename=filename,
                recognized_title=recognized_title,
                match_id=match_id,
                status=status_msg,
                metadata=metadata,
                suggested_new_name=suggested_name,
                parse_source="guessit",
            )

        except Exception as e:
            logger.error("识别失败: filename=%s, error=%s", filename, str(e))
            return MediaRecognitionResponse(
                success=False,
                original_filename=filename,
                status=f"识别失败: {str(e)}",
            )