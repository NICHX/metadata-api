from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import sys
import os

# 确保能找到项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import recognition, config, media_operations, web_ui, filesystem, auth
from api.config import settings, DeploymentMode
from api.dependencies import verify_auth

app = FastAPI(
    title="Metadata API",
    description="媒体归档刮削助手 API",
    version="1.0.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
api_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(api_dir, "static")), name="static")

# 注册路由（所有 API 路由需要 auth 验证，auth_key 留空时自动跳过）
app.include_router(recognition.router, dependencies=[Depends(verify_auth)])
app.include_router(config.router, dependencies=[Depends(verify_auth)])
app.include_router(media_operations.router, dependencies=[Depends(verify_auth)])
app.include_router(web_ui.router)
app.include_router(filesystem.router, dependencies=[Depends(verify_auth)])
app.include_router(auth.router)


@app.get("/")
async def root():
    # 本地模式直接重定向到 Web UI
    if settings.mode == DeploymentMode.LOCAL:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/web-ui")
    return {
        "name": "Metadata API",
        "version": "1.0.0",
        "mode": settings.mode,
        "docs": "/docs",
        "redoc": "/redoc",
        "web_ui": "/web-ui",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
