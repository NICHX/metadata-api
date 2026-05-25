from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import os

# 确保能找到项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import recognition, config, media_operations, web_ui, filesystem
from api.config import settings, DeploymentMode

app = FastAPI(
    title="Media Renamer API",
    description="媒体归档刮削助手 API",
    version="3.3.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(recognition.router)
app.include_router(config.router)
app.include_router(media_operations.router)
app.include_router(web_ui.router)
app.include_router(filesystem.router)


@app.get("/")
async def root():
    # 本地模式直接重定向到 Web UI
    if settings.mode == DeploymentMode.LOCAL:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/web-ui")
    return {
        "name": "Media Renamer API",
        "version": "3.3.0",
        "mode": settings.mode,
        "docs": "/docs",
        "redoc": "/redoc",
        "web_ui": "/web-ui",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
