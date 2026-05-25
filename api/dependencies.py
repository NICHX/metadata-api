from fastapi import HTTPException, Request
from api.config import settings, DeploymentMode


def get_local_mode_only():
    if settings.mode != DeploymentMode.LOCAL:
        raise HTTPException(
            status_code=403,
            detail="此接口仅在本地部署模式下可用"
        )
    return True


def verify_auth(request: Request):
    if not settings.auth_key:
        return True

    auth = request.headers.get("Authorization", "") or request.headers.get("Authentication", "")
    if auth == settings.auth_key or auth == f"Bearer {settings.auth_key}":
        return True

    raise HTTPException(
        status_code=403,
        detail="认证失败，请提供有效的 auth_key",
    )