import os
import shutil
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from api.schemas.common import EpisodeMetadata

logger = logging.getLogger("hardlink_service")

DEFAULT_THRESHOLD = 1_000_000  # 1MB
MODE_HARDLINK = "hardlink"
MODE_COPY = "copy"
MODE_MOVE = "move"

DEFAULT_MOVIE_TEMPLATE = "{title} ({year})/{title}.{ext}"
DEFAULT_TV_TEMPLATE = "{title} ({year})/Season {season:02d}/{title} - S{season:02d}E{episode:02d} - {ep_name}.{ext}"

HISTORY_DIR = ".metadata-api"
HISTORY_FILE = "hardlink_history.json"


def _get_history_path(target_root: str) -> str:
    return os.path.join(target_root, HISTORY_DIR, HISTORY_FILE)


def load_history(target_root: str) -> dict:
    path = _get_history_path(target_root)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("读取硬链接历史失败: %s", e)
    return {"files": []}


def save_history(target_root: str, history: dict):
    path = _get_history_path(target_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def is_linked(src_path: str, target_root: str) -> bool:
    src_norm = os.path.normpath(os.path.abspath(src_path))
    history = load_history(target_root)
    for entry in history.get("files", []):
        if os.path.normpath(os.path.abspath(entry["src"])) == src_norm:
            return True
    return False


def mark_linked(src_path: str, dst_path: str, target_root: str):
    history = load_history(target_root)
    src_norm = os.path.normpath(os.path.abspath(src_path))
    for entry in history.get("files", []):
        if os.path.normpath(os.path.abspath(entry["src"])) == src_norm:
            return
    history.setdefault("files", []).append({
        "src": src_path,
        "dst": dst_path,
        "time": datetime.now().isoformat(),
    })
    save_history(target_root, history)


def _check_same_device(src: str, dst_dir: str) -> bool:
    try:
        src_dev = os.stat(src).st_dev
        dst_dev = os.stat(dst_dir).st_dev
        return src_dev == dst_dev
    except FileNotFoundError:
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)
            dst_dev = os.stat(dst_dir).st_dev
            src_dev = os.stat(src).st_dev
            return src_dev == dst_dev
        return False


def _build_target_path(
    metadata: EpisodeMetadata,
    target_root: str,
    ext: str,
    movie_template: str = DEFAULT_MOVIE_TEMPLATE,
    tv_template: str = DEFAULT_TV_TEMPLATE,
    original_name: str = "",
) -> str:
    data = {
        "title": metadata.title or "Unknown",
        "original_title": metadata.original_title or "",
        "year": metadata.year or "",
        "season": metadata.season or 1,
        "episode": metadata.episode or 1,
        "ep_name": metadata.ep_title or "",
        "ext": ext.lstrip("."),
        "original_name": original_name or (metadata.title or "Unknown") + ext,
    }

    is_tv = bool(metadata.season and metadata.episode)
    template = tv_template if is_tv else movie_template

    path = template.format(**data)
    if not metadata.year:
        path = path.replace(" ()", "")
    dot_ext = f".{data['ext']}"
    path = path.replace(f" - {dot_ext}", dot_ext).replace(f" {dot_ext}", dot_ext)
    return os.path.join(target_root, path)


def hardlink_or_copy(
    src: str,
    dst: str,
    threshold: int = DEFAULT_THRESHOLD,
    mode: str = MODE_HARDLINK,
    fallback_to_copy: bool = True,
) -> str:
    dst_dir = os.path.dirname(dst)
    os.makedirs(dst_dir, exist_ok=True)

    if os.path.exists(dst):
        return dst

    file_size = os.path.getsize(src)

    if mode == MODE_MOVE:
        logger.info("移动: %s → %s", src, dst)
        shutil.move(src, dst)
        return dst

    if mode == MODE_COPY or file_size < threshold:
        logger.info("复制: %s → %s", src, dst)
        shutil.copy2(src, dst)
        return dst

    if mode == MODE_HARDLINK:
        if not _check_same_device(src, dst_dir):
            msg = f"跨分区无法硬链接: {src} → {dst}"
            if fallback_to_copy:
                logger.warning("%s，降级为复制", msg)
                shutil.copy2(src, dst)
                return dst
            raise OSError(msg)
        logger.info("硬链接: %s → %s", src, dst)
        try:
            os.link(src, dst)
        except OSError as e:
            msg = f"硬链接失败（文件系统不支持）: {src} → {dst}: {e}"
            if fallback_to_copy:
                logger.warning("%s，降级为复制", msg)
                shutil.copy2(src, dst)
                return dst
            raise
        return dst

    raise ValueError(f"不支持的整理模式: {mode}")


def organize_file(
    src_path: str,
    src_name: str,
    metadata: EpisodeMetadata,
    target_root: str,
    threshold: int = DEFAULT_THRESHOLD,
    mode: str = MODE_HARDLINK,
    movie_template: str = DEFAULT_MOVIE_TEMPLATE,
    tv_template: str = DEFAULT_TV_TEMPLATE,
    skip_linked: bool = True,
    fallback_to_copy: bool = True,
) -> Dict[str, Any]:
    ext = os.path.splitext(src_name)[1]
    target_path = _build_target_path(metadata, target_root, ext, movie_template, tv_template, original_name=src_name)

    result = {
        "src": src_path,
        "src_name": src_name,
        "dst": target_path,
        "mode": mode,
        "success": False,
        "error": None,
        "linked_skipped": False,
    }

    if not os.path.exists(src_path):
        result["error"] = "源文件不存在"
        return result

    if skip_linked and is_linked(src_path, target_root):
        result["dst"] = target_path
        result["success"] = True
        result["mode"] = "linked_skipped"
        result["linked_skipped"] = True
        return result

    try:
        if os.path.exists(target_path):
            result["dst"] = target_path
            result["success"] = True
            result["mode"] = "already_exists"
            return result

        hardlink_or_copy(src_path, target_path, threshold, mode, fallback_to_copy)
        result["success"] = True
        mark_linked(src_path, target_path, target_root)
        return result
    except Exception as e:
        result["error"] = str(e)
        logger.error("整理失败: %s → %s: %s", src_path, target_path, e)
        return result