from fastapi import HTTPException
from api.config import settings, DeploymentMode


def get_local_mode_only():
    if settings.mode != DeploymentMode.LOCAL:
        raise HTTPException(
            status_code=403,
            detail="此接口仅在本地部署模式下可用"
        )
    return True
