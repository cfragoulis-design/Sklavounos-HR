
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import date

from app.dependencies import get_current_admin, get_db
from app.models import LeaveRequest

router = APIRouter(prefix="/leave-calendar", tags=["leave-calendar"])
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def leave_calendar(
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    requests = (
        db.execute(
            select(LeaveRequest)
            .where(LeaveRequest.status == "approved")
            .order_by(LeaveRequest.date_from.asc())
        )
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        "leave_calendar.html",
        {
            "request": request,
            "requests": requests,
            "today": date.today(),
            "page_title": "Ημερολόγιο Αδειών",
        },
    )
