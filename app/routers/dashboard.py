from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.services import get_dashboard_stats

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    stats = get_dashboard_stats(db)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": admin,
            "stats": stats,
            "page_title": "Dashboard",
            "active_page": "dashboard",
        },
    )
