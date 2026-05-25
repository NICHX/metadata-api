import secrets
import time
from datetime import timedelta

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_COOKIE_NAME = "session_token"
SESSION_DURATION = timedelta(hours=24)
SESSION_DURATION_SECONDS = int(SESSION_DURATION.total_seconds())

_sessions: dict[str, float] = {}


def _clean_expired():
    now = time.time()
    expired = [k for k, t in _sessions.items() if now - t > SESSION_DURATION_SECONDS]
    for k in expired:
        _sessions.pop(k, None)


def is_authenticated(request: Request) -> bool:
    if not settings.web_username or not settings.web_password:
        return True
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return False
    entry_time = _sessions.get(token)
    if entry_time is None:
        return False
    if time.time() - entry_time > SESSION_DURATION_SECONDS:
        _sessions.pop(token, None)
        return False
    return True


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    if not settings.web_username or not settings.web_password:
        return {"success": True, "message": "无需登录"}
    if req.username == settings.web_username and req.password == settings.web_password:
        _clean_expired()
        token = secrets.token_hex(32)
        _sessions[token] = time.time()
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=SESSION_DURATION_SECONDS,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return {"success": True, "message": "登录成功"}
    raise HTTPException(status_code=401, detail="用户名或密码错误")


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"success": True, "message": "已登出"}


@router.get("/check")
async def check_session(request: Request):
    if is_authenticated(request):
        return {"authenticated": True}
    return JSONResponse(status_code=401, content={"authenticated": False})