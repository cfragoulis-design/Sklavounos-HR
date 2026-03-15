from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser, Employee, LeaveRequest, LeaveType
from app.services import (
    calculate_days_requested,
    get_employee_balance_summary,
    recalculate_leave_balances_for_request,
)

router = APIRouter(prefix="/leave-requests", tags=["leave-requests"])
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def leave_requests_list(
    request: Request,
    status_filter: str = "all",
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    stmt = (
        select(LeaveRequest)
        .options(joinedload(LeaveRequest.employee), joinedload(LeaveRequest.leave_type))
        .order_by(LeaveRequest.created_at.desc(), LeaveRequest.id.desc())
    )

    if status_filter != "all":
        stmt = stmt.where(LeaveRequest.status == status_filter)
    if employee_id:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)

    leave_requests = db.execute(stmt).scalars().all()
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name.asc())).scalars().all()

    return templates.TemplateResponse(
        "leave_requests.html",
        {
            "request": request,
            "admin": admin,
            "leave_requests": leave_requests,
            "employees": employees,
            "status_filter": status_filter,
            "employee_id": employee_id,
            "page_title": "Αιτήματα αδειών",
            "active_page": "leave_requests",
        },
    )


@router.get("/new")
def leave_request_new(
    request: Request,
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name.asc())).scalars().all()
    leave_types = db.execute(select(LeaveType).where(LeaveType.is_active.is_(True)).order_by(LeaveType.name.asc())).scalars().all()

    selected_employee = employee_id or (employees[0].id if employees else None)
    balance_summary = get_employee_balance_summary(db, selected_employee, datetime.utcnow().year) if selected_employee else None
    db.flush()

    return templates.TemplateResponse(
        "leave_request_form.html",
        {
            "request": request,
            "admin": admin,
            "employees": employees,
            "leave_types": leave_types,
            "selected_employee_id": selected_employee,
            "balance_summary": balance_summary,
            "page_title": "Νέο αίτημα άδειας",
            "active_page": "leave_requests",
            "error": None,
            "form_data": {
                "employee_id": selected_employee,
                "leave_type_id": None,
                "date_from": "",
                "date_to": "",
                "note": "",
            },
        },
    )


@router.post("")
def leave_request_create(
    request: Request,
    employee_id: int = Form(...),
    leave_type_id: int = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name.asc())).scalars().all()
    leave_types = db.execute(select(LeaveType).where(LeaveType.is_active.is_(True)).order_by(LeaveType.name.asc())).scalars().all()

    try:
        dt_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        dt_to = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        dt_from = None
        dt_to = None

    employee = db.get(Employee, employee_id)
    leave_type = db.get(LeaveType, leave_type_id)

    error = None
    if not employee:
        error = "Ο εργαζόμενος δεν βρέθηκε."
    elif not leave_type:
        error = "Ο τύπος άδειας δεν βρέθηκε."
    elif not dt_from or not dt_to:
        error = "Οι ημερομηνίες είναι υποχρεωτικές."
    elif dt_to < dt_from:
        error = "Η ημερομηνία 'έως' δεν μπορεί να είναι πριν από την 'από'."

    if error:
        balance_summary = get_employee_balance_summary(db, employee_id, datetime.utcnow().year) if employee_id else None
        return templates.TemplateResponse(
            "leave_request_form.html",
            {
                "request": request,
                "admin": admin,
                "employees": employees,
                "leave_types": leave_types,
                "selected_employee_id": employee_id,
                "balance_summary": balance_summary,
                "page_title": "Νέο αίτημα άδειας",
                "active_page": "leave_requests",
                "error": error,
                "form_data": {
                    "employee_id": employee_id,
                    "leave_type_id": leave_type_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "note": note,
                },
            },
            status_code=400,
        )

    item = LeaveRequest(
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        date_from=dt_from,
        date_to=dt_to,
        days_requested=calculate_days_requested(dt_from, dt_to),
        note=(note or "").strip() or None,
        status="pending",
    )
    db.add(item)
    db.commit()
    return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{leave_request_id}/approve")
def leave_request_approve(
    leave_request_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    item = db.get(LeaveRequest, leave_request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Leave request not found")

    item.status = "approved"
    item.approved_by = admin.username
    item.approved_at = datetime.utcnow()
    db.add(item)
    recalculate_leave_balances_for_request(db, item)
    db.commit()
    return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{leave_request_id}/reject")
def leave_request_reject(
    leave_request_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    item = db.get(LeaveRequest, leave_request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Leave request not found")

    item.status = "rejected"
    item.approved_by = admin.username
    item.approved_at = datetime.utcnow()
    db.add(item)
    recalculate_leave_balances_for_request(db, item)
    db.commit()
    return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{leave_request_id}/cancel")
def leave_request_cancel(
    leave_request_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    item = db.get(LeaveRequest, leave_request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Leave request not found")

    item.status = "cancelled"
    item.approved_by = admin.username
    item.approved_at = datetime.utcnow()
    db.add(item)
    recalculate_leave_balances_for_request(db, item)
    db.commit()
    return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)
