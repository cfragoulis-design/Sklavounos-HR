from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models import Employee, LeaveBalance, LeaveRequest, LeaveType
from app.services import write_audit_log

router = APIRouter(prefix="/employees", tags=["balance-adjustment"])
templates = Jinja2Templates(directory="app/templates")


def _calc_used_days(db: Session, employee_id: int, year: int) -> int:
    used_days = db.scalar(
        select(func.coalesce(func.sum(LeaveRequest.days_requested), 0))
        .select_from(LeaveRequest)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == "approved",
            LeaveType.counts_against_balance.is_(True),
            func.extract("year", LeaveRequest.date_from) == year,
        )
    ) or 0
    return int(used_days)


@router.get("/{employee_id}/balance-adjustment")
def employee_balance_adjustment(
    employee_id: int,
    request: Request,
    year: int | None = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)

    selected_year = year or datetime.now().year

    balance = db.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.year == selected_year,
        )
    )

    used_days = _calc_used_days(db, employee_id, selected_year)

    if balance:
        entitled_days = balance.entitled_days
        remaining_days = balance.remaining_days
    else:
        entitled_days = employee.annual_leave_days or 0
        remaining_days = entitled_days - used_days

    return templates.TemplateResponse(
        "balance_adjustment.html",
        {
            "request": request,
            "admin": admin,
            "employee": employee,
            "selected_year": selected_year,
            "entitled_days": entitled_days,
            "used_days": used_days,
            "remaining_days": remaining_days,
            "page_title": f"Υπόλοιπο Αδειών: {employee.full_name}",
            "active_page": "employees",
        },
    )


@router.post("/{employee_id}/balance-adjustment")
def employee_balance_adjustment_save(
    employee_id: int,
    year: int = Form(...),
    entitled_days: int = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)

    used_days = _calc_used_days(db, employee_id, year)

    balance = db.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.year == year,
        )
    )

    if not balance:
        balance = LeaveBalance(
            employee_id=employee_id,
            year=year,
            entitled_days=entitled_days,
            used_days=used_days,
            remaining_days=max(entitled_days - used_days, 0),
        )
        db.add(balance)
    else:
        balance.entitled_days = entitled_days
        balance.used_days = used_days
        balance.remaining_days = max(entitled_days - used_days, 0)

    db.commit()

    details = f"Manual balance adjustment for year {year}. entitled_days={entitled_days}. used_days={used_days}. reason={reason or '-'}"
    write_audit_log(db, "leave_balance", balance.id, "manual_adjustment", admin.username, details)
    db.commit()

    return RedirectResponse(
        url=f"/employees/{employee_id}/balance-adjustment?year={year}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
