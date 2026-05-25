from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional, List
import os
import re
import platform
import json
import asyncio
from collections import deque
from api.dependencies import get_local_mode_only
from api.schemas.media import (
    FileSystemItem,
    DirectoryContentsResponse,
    ScanMediaFilesResponse,
    FileInfo,
)
from utils.helpers import DEFAULT_VIDEO_EXTS

router = APIRouter(
    prefix="/api/v1/filesystem",
    tags=["filesystem"],
    dependencies=[Depends(get_local_mode_only)],
)

SEASON_RE = re.compile(r"(?:season\s*|s)(\d+)|第\s*(\d+)\s*季", re.IGNORECASE)


def get_media_extensions():
    return [ext.strip().lower() for ext in DEFAULT_VIDEO_EXTS.split(",") if ext.strip()]


def is_media_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in get_media_extensions()


def get_file_group_id(filepath: str) -> str:
    """根据文件路径推断分组ID（剧集目录）。
    
    如果父目录是季文件夹（Season 1, S01, 第1季），返回祖父目录作为分组ID；
    否则返回父目录作为分组ID。
    """
    dir_path = os.path.dirname(os.path.normpath(filepath))
    parent_name = os.path.basename(dir_path)
    if SEASON_RE.search(parent_name):
        grandparent = os.path.dirname(dir_path)
        if grandparent and grandparent != dir_path:
            return grandparent
    return dir_path


def get_root_dirs():
    system = platform.system()
    if system == "Windows":
        drives = []
        import string
        try:
            from ctypes import windll
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(f"{letter}:\\")
                bitmask >>= 1
        except Exception:
            drives = ["C:\\"]
        return drives
    else:
        return ["/"]


def normalize_path(path):
    return os.path.normpath(path)


@router.get("/browse", response_model=DirectoryContentsResponse)
async def browse_directory(
    path: Optional[str] = Query(None),
    show_hidden: bool = Query(False),
):
    try:
        if not path:
            roots = get_root_dirs()
            items = [
                FileSystemItem(
                    name=root,
                    path=root,
                    is_dir=True,
                    size=None,
                    extension=None,
                )
                for root in roots
            ]
            return DirectoryContentsResponse(
                current_path="",
                parent_path=None,
                items=items,
            )

        path = normalize_path(path)

        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"Directory not found: {path}")

        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

        parent_dir = os.path.dirname(path)
        parent_path = parent_dir if parent_dir and parent_dir != path else None

        items = []
        try:
            for name in os.listdir(path):
                if not show_hidden and name.startswith("."):
                    continue

                item_path = os.path.join(path, name)
                is_dir = os.path.isdir(item_path)
                size = None
                extension = None

                if not is_dir:
                    try:
                        size = os.path.getsize(item_path)
                    except:
                        pass
                    _, ext = os.path.splitext(name)
                    extension = ext.lower() if ext else None

                items.append(
                    FileSystemItem(
                        name=name,
                        path=item_path,
                        is_dir=is_dir,
                        size=size,
                        extension=extension,
                    )
                )
        except PermissionError:
            raise HTTPException(status_code=403, detail=f"No access: {path}")

        items.sort(key=lambda x: (not x.is_dir, x.name.lower()))

        return DirectoryContentsResponse(
            current_path=path,
            parent_path=parent_path,
            items=items,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Browse failed: {str(e)}")


@router.post("/scan", response_model=ScanMediaFilesResponse)
async def scan_media_files(
    path: str = Query(...),
    recursive: bool = Query(True),
):
    try:
        path = normalize_path(path)

        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"Directory not found: {path}")

        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

        media_files = []

        def scan_dir(current_path):
            try:
                for name in os.listdir(current_path):
                    item_path = os.path.join(current_path, name)
                    if os.path.isdir(item_path):
                        if recursive:
                            scan_dir(item_path)
                    elif os.path.isfile(item_path):
                        if is_media_file(name):
                            try:
                                size = os.path.getsize(item_path)
                            except:
                                size = None
                            media_files.append(
                                FileInfo(path=item_path, name=name, size=size, group_id=get_file_group_id(item_path))
                            )
            except PermissionError:
                pass

        scan_dir(path)
        media_files.sort(key=lambda x: x.name.lower())

        return ScanMediaFilesResponse(
            scanned_path=path,
            media_files=media_files,
            total_count=len(media_files),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")


@router.post("/scan/stream")
async def scan_media_files_stream(
    path: str = Query(...),
    recursive: bool = Query(True),
):
    async def generate_scan_results():
        try:
            target_path = normalize_path(path)

            if not os.path.exists(target_path):
                yield json.dumps({"type": "error", "message": f"Directory not found: {target_path}"}) + "\n"
                return

            if not os.path.isdir(target_path):
                yield json.dumps({"type": "error", "message": f"Not a directory: {target_path}"}) + "\n"
                return

            media_files = []
            scanned_dirs = 0
            directories_to_scan = deque([target_path])

            while directories_to_scan:
                current_path = directories_to_scan.popleft()
                scanned_dirs += 1

                try:
                    yield json.dumps({
                        "type": "progress",
                        "scanned_dirs": scanned_dirs,
                        "found_files": len(media_files),
                        "current_path": current_path,
                    }) + "\n"

                    if os.path.exists(current_path):
                        for name in os.listdir(current_path):
                            item_path = os.path.join(current_path, name)

                            if os.path.isdir(item_path) and recursive:
                                directories_to_scan.append(item_path)
                            elif os.path.isfile(item_path) and is_media_file(name):
                                try:
                                    size = os.path.getsize(item_path)
                                except:
                                    size = None
                                media_files.append({
                                    "path": item_path,
                                    "name": name,
                                    "size": size,
                                    "group_id": get_file_group_id(item_path),
                                })

                except PermissionError:
                    continue
                except Exception:
                    continue

                await asyncio.sleep(0.01)

            media_files.sort(key=lambda x: x["name"].lower())

            yield json.dumps({
                "type": "complete",
                "scanned_path": target_path,
                "media_files": media_files,
                "total_count": len(media_files),
            }) + "\n"

        except Exception as e:
            yield json.dumps({"type": "error", "message": f"Scan failed: {str(e)}"}) + "\n"

    return StreamingResponse(
        generate_scan_results(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
