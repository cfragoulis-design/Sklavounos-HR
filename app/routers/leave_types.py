from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser, LeaveType

router = APIRouter(prefix="/leave-types", tags=["leave-types"])
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def leave_types_list(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    leave_types = db.execute(select(LeaveType).order_by(LeaveType.name.asc())).scalars().all()
    return templates.TemplateResponse(
        "leave_types.html",
        {
            "request": request,
            "admin": admin,
            "leave_types": leave_types,
            "page_title": "Τύποι αδειών",
            "active_page": "leave_types",
        },
    )
