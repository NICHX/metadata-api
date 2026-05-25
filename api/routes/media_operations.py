from fastapi import APIRouter, Depends, Body, HTTPException, Query, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from typing import List
import requests
import json
import asyncio

from api.dependencies import get_local_mode_only
from api.schemas.media import (
    FileInfo,
    PreviewRenameRequest,
    PreviewRenameResponse,
    RenamePreviewResult,
    RenameRequest,
    OrganizeRequest,
    ScrapeRequest,
)
from api.services.recognition_service import RecognitionService
from api.services.media_operations_service import MediaOperationsService, _estimate_ai_cost
from api.services.ai_service import get_and_reset_token_usage

# TMDb 图片 CDN 基础地址
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

router = APIRouter(
    prefix="/api/v1/media",
    tags=["media-operations"],
    dependencies=[Depends(get_local_mode_only)],
)


@router.post("/preview-rename", response_model=PreviewRenameResponse)
async def preview_rename(
    files: List[FileInfo] = Body(
        ...,
        examples=[
            [
                {"path": "/movies/Breaking.Bad.S01E01.Pilot.mkv", "name": "Breaking.Bad.S01E01.Pilot.mkv"}
            ]
        ]
    ),
    tv_template: str = Body(None, description="剧集命名模板"),
    movie_template: str = Body(None, description="电影命名模板"),
):
    """返回重命名预览，不实际操作文件"""
    results = []

    for file_info in files:
        try:
            result = await RecognitionService.recognize_media(
                filename=file_info.name,
                filepath=file_info.path,
            )
            preview_result = RenamePreviewResult(
                original=file_info.name,
                suggested=result.suggested_new_name or file_info.name,
                target_path=None,
                metadata=result.metadata,
            )
            results.append(preview_result)
        except Exception as e:
            results.append(
                RenamePreviewResult(
                    original=file_info.name,
                    suggested=file_info.name,
                    target_path=None,
                    metadata=None,
                )
            )

    return PreviewRenameResponse(results=results)


@router.post("/scrape")
async def scrape_metadata(
    request: ScrapeRequest = Body(...),
):
    """刮削 NFO 和图片（仅本地模式可用）"""
    if not request.files:
        return {
            "success": False,
            "message": "没有指定要刮削的文件"
        }
    
    result = await MediaOperationsService.batch_scrape(
        files=request.files,
        source=request.source,
        download_images=request.download_images,
        write_nfo_flag=request.write_nfo
    )

    response_data = {
        "success": result.get("failed", 0) == 0,
        "total": result.get("total", 0),
        "success_count": result.get("success", 0),
        "failed_count": result.get("failed", 0),
        "results": result.get("results", [])
    }
    if result.get("token_usage"):
        response_data["token_usage"] = result["token_usage"]

    return response_data


@router.post("/scrape/stream")
async def scrape_metadata_stream(request: ScrapeRequest = Body(...)):
    """流式刮削 - 实时返回每个文件的刮削结果"""
    if not request.files:
        return StreamingResponse(
            iter([json.dumps({"type": "error", "message": "没有指定要刮削的文件"}) + "\n"]),
            media_type="application/x-ndjson"
        )
    
    async def generate_scrape_results():
        total = len(request.files)
        
        for idx, file_info in enumerate(request.files, 1):
            try:
                result = await MediaOperationsService.scrape_metadata(
                    file_info=file_info,
                    source=request.source,
                    download_images=request.download_images,
                    write_nfo_flag=request.write_nfo
                )
                
                # 发送刮削结果
                yield json.dumps({
                    "type": "result",
                    "index": idx,
                    "total": total,
                    "success": result.get("success", False),
                    "data": {
                        "success": result.get("success", False),
                        "original_path": result.get("original_path", ""),
                        "original_name": result.get("original_name", ""),
                        "recognized_title": result.get("recognized_title", ""),
                        "match_id": result.get("match_id", ""),
                        "status": result.get("status", ""),
                        "nfo_written": result.get("nfo_written", []),
                        "images_downloaded": result.get("images_downloaded", []),
                        "errors": result.get("errors", []),
                    }
                }) + "\n"
                
            except Exception as e:
                # 发送错误结果
                yield json.dumps({
                    "type": "result",
                    "index": idx,
                    "total": total,
                    "success": False,
                    "data": {
                        "success": False,
                        "original_path": file_info.path,
                        "original_name": file_info.name,
                        "status": f"刮削失败: {str(e)}",
                        "errors": [str(e)],
                    }
                }) + "\n"
            
            # 添加小延迟以避免阻塞
            await asyncio.sleep(0.01)
        
        # 发送完成消息
        token_usage_list = get_and_reset_token_usage()
        complete_msg = {"type": "complete", "total": total}
        if token_usage_list:
            total_prompt = sum(u.get("prompt_tokens", 0) for u in token_usage_list)
            total_completion = sum(u.get("completion_tokens", 0) for u in token_usage_list)
            total_tokens = sum(u.get("total_tokens", 0) for u in token_usage_list)
            costs = _estimate_ai_cost(token_usage_list)
            complete_msg["token_usage"] = {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "calls": len(token_usage_list),
                "cost_cache_miss": costs["cache_miss"],
                "cost_cache_hit": costs["cache_hit"],
            }
        yield json.dumps(complete_msg) + "\n"
    
    return StreamingResponse(
        generate_scrape_results(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/rename")
async def rename_files(request: RenameRequest = Body(...)):
    """原地重命名文件（仅本地模式可用）"""
    if request.dry_run:
        return {"success": True, "message": "预览模式，未执行任何操作", "dry_run": True}
    
    # TODO: 实现真实的重命名逻辑
    return {"success": True, "message": "重命名功能开发中", "results": []}


@router.post("/organize")
async def organize_files(request: OrganizeRequest = Body(...)):
    """归档整理（仅本地模式可用）"""
    if request.dry_run:
        return {"success": True, "message": "预览模式，未执行任何操作", "dry_run": True}
    
    # TODO: 实现真实的归档逻辑
    return {"success": True, "message": "归档整理功能开发中", "results": []}


@router.get("/image")
async def get_image(
    path: str = Query(..., description="图片相对路径，如 /o25Tk1FYQi2BLk0OEAvx2h69QvB.jpg"),
    size: str = Query("original", description="图片尺寸: original/w500/w342/w185"),
):
    """代理 TMDb 图片，客户端直接通过此接口获取海报等图片"""
    if not path:
        raise HTTPException(status_code=400, detail="缺少图片路径参数 path")
    if path.startswith("http"):
        image_url = path
    else:
        image_url = f"{TMDB_IMAGE_BASE}/{size}{path}"
    try:
        resp = requests.get(image_url, timeout=15)
        resp.raise_for_status()
        return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"获取图片失败: {str(e)}")


@router.get("/image-url")
async def get_image_url(
    path: str = Query(..., description="图片相对路径，如 /o25Tk1FYQi2BLk0OEAvx2h69QvB.jpg"),
    size: str = Query("original", description="图片尺寸: original/w500/w342/w185"),
):
    """返回 TMDb 图片完整 URL，客户端自行加载"""
    if not path:
        raise HTTPException(status_code=400, detail="缺少图片路径参数 path")
    if path.startswith("http"):
        full_url = path
    else:
        full_url = f"{TMDB_IMAGE_BASE}/{size}{path}"
    return {"url": full_url, "size": size}
