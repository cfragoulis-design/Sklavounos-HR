from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser, LeaveRequest

router = APIRouter(prefix="/leave-requests", tags=["leave-requests"])
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def leave_requests_list(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    requests = (
        db.execute(
            select(LeaveRequest)
            .options(joinedload(LeaveRequest.employee), joinedload(LeaveRequest.leave_type))
            .order_by(LeaveRequest.created_at.desc())
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        "leave_requests.html",
        {
            "request": request,
            "admin": admin,
            "leave_requests": requests,
            "page_title": "Αιτήματα αδειών",
            "active_page": "leave_requests",
        },
    )


@router.get("/new")
def leave_request_new(request: Request, admin: AdminUser = Depends(get_current_admin)):
    return templates.TemplateResponse(
        "placeholder.html",
        {
            "request": request,
            "admin": admin,
            "page_title": "Νέο αίτημα άδειας",
            "active_page": "leave_requests",
            "title": "Νέο αίτημα άδειας",
            "message": "Η φόρμα καταχώρησης άδειας θα μπει στο επόμενο patch.",
        },
    )
