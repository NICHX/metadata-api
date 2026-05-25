from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from api.config import settings
from utils.helpers import clear_api_cache_file
from api.services.recognition_service import _ai_result_cache

router = APIRouter(prefix="/api/v1/config", tags=["config"])


class ConfigUpdate(BaseModel):
    tmdb_api_key: Optional[str] = None
    bgm_api_key: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_base_url: Optional[str] = None
    ai_model: Optional[str] = None
    ai_max_tokens: Optional[int] = None


@router.get("")
async def get_config():
    return {
        "mode": settings.mode,
        "tmdb_api_key_set": bool(settings.tmdb_api_key),
        "bgm_api_key_set": bool(settings.bgm_api_key),
        "ai_api_key_set": bool(settings.ai_api_key),
        "ai_base_url": settings.ai_base_url,
        "ai_model": settings.ai_model,
        "ai_max_tokens": settings.ai_max_tokens,
    }


@router.put("")
async def update_config(config: ConfigUpdate):
    updated = False
    if config.tmdb_api_key is not None:
        settings.tmdb_api_key = config.tmdb_api_key
        updated = True
    if config.bgm_api_key is not None:
        settings.bgm_api_key = config.bgm_api_key
        updated = True
    if config.ai_api_key is not None:
        settings.ai_api_key = config.ai_api_key
        updated = True
    if config.ai_base_url is not None:
        settings.ai_base_url = config.ai_base_url
        updated = True
    if config.ai_model is not None:
        settings.ai_model = config.ai_model
        updated = True
    if config.ai_max_tokens is not None:
        settings.ai_max_tokens = config.ai_max_tokens
        updated = True

    if updated:
        saved = settings.save_to_file()
        return {
            "success": True,
            "message": "配置已更新",
            "saved_to_file": saved,
        }

    return {"success": True, "message": "没有需要更新的配置"}


@router.post("/clear-cache")
async def clear_cache():
    try:
        clear_api_cache_file()
        _ai_result_cache.clear()
        return {"success": True, "message": "缓存已清除"}
    except Exception as e:
        return {"success": False, "message": f"清除缓存失败: {str(e)}"}