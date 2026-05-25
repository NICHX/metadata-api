from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
)


@router.get("/web-ui", include_in_schema=False)
async def web_ui(request: Request):
    return templates.TemplateResponse(request, "web_ui.html")