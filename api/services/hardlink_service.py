import os
import shutil
import logging
from typing import Dict, Any, Optional

from api.schemas.common import EpisodeMetadata

logger = logging.getLogger("hardlink_service")

DEFAULT_THRESHOLD = 1_000_000  # 1MB
MODE_HARDLINK = "hardlink"
MODE_COPY = "copy"
MODE_MOVE = "move"

DEFAULT_MOVIE_TEMPLATE = "{title} ({year})/{title}.{ext}"
DEFAULT_TV_TEMPLATE = "{title}/Season {season:02d}/{title} - S{season:02d}E{episode:02d}.{ext}"


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
) -> str:
    data = {
        "title": metadata.title or "Unknown",
        "original_title": metadata.original_title or "",
        "year": metadata.year or "",
        "season": metadata.season or 1,
        "episode": metadata.episode or 1,
        "ext": ext.lstrip("."),
    }

    is_tv = bool(metadata.season and metadata.episode)
    template = tv_template if is_tv else movie_template

    path = template.format(**data)
    return os.path.join(target_root, path)


def hardlink_or_copy(
    src: str,
    dst: str,
    threshold: int = DEFAULT_THRESHOLD,
    mode: str = MODE_HARDLINK,
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
            logger.warning("跨分区无法硬链接，降级为复制: %s → %s", src, dst)
            shutil.copy2(src, dst)
            return dst
        logger.info("硬链接: %s → %s", src, dst)
        os.link(src, dst)
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
) -> Dict[str, Any]:
    ext = os.path.splitext(src_name)[1]
    target_path = _build_target_path(metadata, target_root, ext, movie_template, tv_template)

    result = {
        "src": src_path,
        "src_name": src_name,
        "dst": target_path,
        "mode": mode,
        "success": False,
        "error": None,
    }

    if not os.path.exists(src_path):
        result["error"] = "源文件不存在"
        return result

    try:
        if os.path.exists(target_path):
            result["dst"] = target_path
            result["success"] = True
            result["mode"] = "already_exists"
            return result

        hardlink_or_copy(src_path, target_path, threshold, mode)
        result["success"] = True
        return result
    except Exception as e:
        result["error"] = str(e)
        logger.error("整理失败: %s → %s: %s", src_path, target_path, e)
        return result