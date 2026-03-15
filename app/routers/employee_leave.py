
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.dependencies import get_current_admin, get_db
from app.models import Employee, LeaveRequest
from app.services import get_employee_balance_summary

router = APIRouter(prefix="/employees", tags=["employee-leave"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/{employee_id}/leave")
def employee_leave_balance(
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        return {"error": "Employee not found"}

    balance = get_employee_balance_summary(db, employee_id, 2026)

    requests = (
        db.execute(
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id)
            .order_by(LeaveRequest.date_from.desc())
        )
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        "employee_leave_balance.html",
        {
            "request": request,
            "employee": employee,
            "balance": balance,
            "requests": requests,
            "page_title": f"Άδειες: {employee.full_name}",
        },
    )
