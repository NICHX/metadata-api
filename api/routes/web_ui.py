from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
import os
import json
import asyncio

router = APIRouter()

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
)


@router.get("/api/v1/media/logs/stream")
async def stream_logs():
    """SSE 流式返回日志"""
    from utils.log_buffer import get_logs

    async def event_stream():
        from utils.log_buffer import clear_logs
        clear_logs()
        last_count = -1
        while True:
            logs = await get_logs(500)
            current_count = len(logs)
            if current_count != last_count:
                last_count = current_count
                yield f"data: {json.dumps({'logs': logs, 'count': current_count})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/web-ui/login")
async def login_page(request: Request):
    from api.routes.auth import is_authenticated
    if is_authenticated(request):
        return RedirectResponse(url="/web-ui")
    return templates.TemplateResponse(request, "login.html")


@router.get("/web-ui")
async def web_ui(request: Request):
    from api.routes.auth import is_authenticated
    if not is_authenticated(request):
        return RedirectResponse(url="/web-ui/login")
    from api.config import settings
    return templates.TemplateResponse(request, "web_ui.html", {
        "auth_key": settings.auth_key or "",
    })