from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
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
    return templates.TemplateResponse(request, "web_ui.html")