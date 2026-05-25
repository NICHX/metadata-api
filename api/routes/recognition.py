from fastapi import APIRouter, HTTPException, Body, Query
from fastapi.responses import StreamingResponse
from typing import List
import asyncio
import json

from api.schemas.media import (
    MediaFileParseRequest,
    MediaFileParseResponse,
    MediaRecognitionRequest,
    MediaRecognitionResponse,
    BatchRecognitionRequest,
    BatchRecognitionResponse,
)
from api.services.recognition_service import RecognitionService, prepopulate_ai_cache

router = APIRouter(prefix="/api/v1/recognition", tags=["recognition"])


@router.post("/parse", response_model=MediaFileParseResponse)
async def parse_filename(
    filename: str = Body(
        ...,
        examples=["Breaking.Bad.S01E01.Pilot.mkv"],
        description="媒体文件名"
    )
):
    try:
        request = MediaFileParseRequest(filename=filename)
        result = RecognitionService.parse_filename(request.filename)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recognize", response_model=MediaRecognitionResponse)
async def recognize_media(
    filename: str = Body(..., examples=["Breaking.Bad.S01E01.Pilot.mkv"]),
    filepath: str = Body(None, examples=["/path/to/Breaking.Bad.S01E01.Pilot.mkv"]),
    source: str = Body("siliconflow_tmdb", description="数据源: siliconflow_tmdb / siliconflow_bgm"),
    media_type_override: str = Body(None, description="媒体类型: auto / movie / tv"),
):
    try:
        request = MediaRecognitionRequest(
            filename=filename,
            filepath=filepath,
            source=source,
            media_type_override=media_type_override,
        )
        result = await RecognitionService.recognize_media(
            filename=request.filename,
            filepath=request.filepath,
            source=request.source,
            media_type_override=request.media_type_override,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-recognize", response_model=BatchRecognitionResponse)
async def batch_recognize(request: BatchRecognitionRequest = Body(...)):
    results = []
    success_count = 0
    failed_count = 0

    await prepopulate_ai_cache(request.files)

    async def recognize_single(file_req):
        try:
            result = await RecognitionService.recognize_media(
                filename=file_req.filename,
                filepath=file_req.filepath,
                source=request.source,
                media_type_override=file_req.media_type_override,
                group_id=file_req.group_id,
            )
            return result
        except Exception as e:
            return MediaRecognitionResponse(
                success=False,
                original_filename=file_req.filename or "",
                status=f"处理失败: {str(e)}",
            )

    tasks = [recognize_single(file_req) for file_req in request.files]
    results = await asyncio.gather(*tasks)

    for result in results:
        if result.success:
            success_count += 1
        else:
            failed_count += 1

    return BatchRecognitionResponse(
        total=len(request.files),
        success=success_count,
        failed=failed_count,
        results=results,
    )


@router.post("/batch-recognize/stream")
async def batch_recognize_stream(request: BatchRecognitionRequest = Body(...)):
    """流式批量识别 - 实时返回每个文件的识别结果"""

    async def generate_recognition_results():
        total = len(request.files)

        await prepopulate_ai_cache(request.files)

        for idx, file_req in enumerate(request.files, 1):
            try:
                result = await RecognitionService.recognize_media(
                    filename=file_req.filename,
                    filepath=file_req.filepath,
                    source=request.source,
                    media_type_override=file_req.media_type_override,
                    group_id=file_req.group_id,
                )
                
                # 发送识别结果
                yield json.dumps({
                    "type": "result",
                    "index": idx,
                    "total": total,
                    "success": result.success,
                    "data": {
                        "success": result.success,
                        "original_filename": result.original_filename,
                        "status": result.status,
                        "recognized_title": result.recognized_title,
                        "match_id": result.match_id,
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
                        "original_filename": file_req.filename or "",
                        "status": f"识别失败: {str(e)}",
                    }
                }) + "\n"
            
            # 添加小延迟以避免阻塞
            await asyncio.sleep(0.01)
        
        # 发送完成消息
        yield json.dumps({"type": "complete", "total": total}) + "\n"
    
    return StreamingResponse(
        generate_recognition_results(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )