from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser
from app.services import get_dashboard_stats

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
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


@router.get("/calendar")
def calendar_page(request: Request, admin: AdminUser = Depends(get_current_admin)):
    return templates.TemplateResponse(
        "placeholder.html",
        {
            "request": request,
            "admin": admin,
            "page_title": "Ημερολόγιο",
            "active_page": "calendar",
            "title": "Ημερολόγιο",
            "message": "Το ημερολόγιο θα μπει στο επόμενο βήμα του project.",
        },
    )
