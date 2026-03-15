from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser, Employee, LeaveRequest, LeaveType
from app.services import (
    calculate_days_requested,
    get_active_leave_types,
    get_employee_balance_summary,
    get_leave_request_with_relations,
    recalculate_leave_balances_for_request,
    write_audit_log,
)

router = APIRouter(prefix="/leave-requests", tags=["leave-requests"])
templates = Jinja2Templates(directory="app/templates")


def _parse_date(value: str):
    return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()


def _render_form(
    request: Request,
    admin: AdminUser,
    db: Session,
    leave_request: LeaveRequest | None,
    error: str | None = None,
    form_data: dict | None = None,
):
    employees = db.execute(
        select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name.asc())
    ).scalars().all()
    leave_types = get_active_leave_types(db)

    selected_employee_id = None
    if form_data and form_data.get("employee_id"):
        try:
            selected_employee_id = int(form_data.get("employee_id"))
        except (TypeError, ValueError):
            selected_employee_id = None
    elif leave_request:
        selected_employee_id = leave_request.employee_id

    balance = None
    if selected_employee_id:
        balance = get_employee_balance_summary(db, selected_employee_id, datetime.now().year)

    return templates.TemplateResponse(
        "leave_request_form.html",
        {
            "request": request,
            "admin": admin,
            "leave_request": leave_request,
            "employees": employees,
            "leave_types": leave_types,
            "balance": balance,
            "error": error,
            "form_data": form_data or {},
            "page_title": "Νέο αίτημα άδειας",
            "active_page": "leave-requests",
        },
        status_code=status.HTTP_400_BAD_REQUEST if error else status.HTTP_200_OK,
    )


@router.get("")
def leave_requests_list(
    request: Request,
    employee_id: int | None = None,
    status_filter: str = "all",
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    stmt = select(LeaveRequest).options(
        joinedload(LeaveRequest.employee),
        joinedload(LeaveRequest.leave_type),
    )

    if employee_id:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)

    if status_filter != "all":
        stmt = stmt.where(LeaveRequest.status == status_filter)

    leave_requests = db.execute(stmt.order_by(LeaveRequest.created_at.desc())).scalars().all()
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name.asc())).scalars().all()

    return templates.TemplateResponse(
        "leave_requests.html",
        {
            "request": request,
            "admin": admin,
            "leave_requests": leave_requests,
            "employees": employees,
            "employee_id": employee_id,
            "status_filter": status_filter,
            "page_title": "Αιτήματα Αδειών",
            "active_page": "leave-requests",
        },
    )


@router.get("/new")
def leave_request_new(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    return _render_form(request, admin, db, None)


@router.post("/new")
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
    form_data = {
        "employee_id": employee_id,
        "leave_type_id": leave_type_id,
        "date_from": date_from,
        "date_to": date_to,
        "note": note,
    }

    employee = db.get(Employee, employee_id)
    leave_type = db.get(LeaveType, leave_type_id)

    if not employee:
        return _render_form(request, admin, db, None, error="Δεν βρέθηκε εργαζόμενος.", form_data=form_data)
    if not leave_type:
        return _render_form(request, admin, db, None, error="Δεν βρέθηκε τύπος άδειας.", form_data=form_data)

    try:
        parsed_from = _parse_date(date_from)
        parsed_to = _parse_date(date_to)
    except ValueError:
        return _render_form(request, admin, db, None, error="Μη έγκυρες ημερομηνίες.", form_data=form_data)

    if parsed_to < parsed_from:
        return _render_form(request, admin, db, None, error="Η ημερομηνία λήξης δεν μπορεί να είναι πριν από την έναρξη.", form_data=form_data)

    leave_request = LeaveRequest(
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        date_from=parsed_from,
        date_to=parsed_to,
        days_requested=calculate_days_requested(parsed_from, parsed_to),
        note=(note or "").strip() or None,
        status="pending",
    )
    db.add(leave_request)
    db.commit()
    db.refresh(leave_request)

    write_audit_log(db, "leave_request", leave_request.id, "create", admin.username, f"Created leave request for {employee.full_name}")
    db.commit()

    return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{request_id}/approve")
def leave_request_approve(
    request_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    leave_request = get_leave_request_with_relations(db, request_id)
    if not leave_request:
        return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)

    leave_request.status = "approved"
    leave_request.approved_by = admin.username
    leave_request.approved_at = datetime.utcnow()

    recalculate_leave_balances_for_request(db, leave_request)
    db.commit()

    write_audit_log(db, "leave_request", leave_request.id, "approve", admin.username, f"Approved leave request #{leave_request.id}")
    db.commit()

    return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{request_id}/reject")
def leave_request_reject(
    request_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    leave_request = get_leave_request_with_relations(db, request_id)
    if not leave_request:
        return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)

    leave_request.status = "rejected"
    leave_request.approved_by = admin.username
    leave_request.approved_at = datetime.utcnow()

    recalculate_leave_balances_for_request(db, leave_request)
    db.commit()

    write_audit_log(db, "leave_request", leave_request.id, "reject", admin.username, f"Rejected leave request #{leave_request.id}")
    db.commit()

    return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{request_id}/cancel")
def leave_request_cancel(
    request_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    leave_request = get_leave_request_with_relations(db, request_id)
    if not leave_request:
        return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)

    leave_request.status = "cancelled"
    recalculate_leave_balances_for_request(db, leave_request)
    db.commit()

    write_audit_log(db, "leave_request", leave_request.id, "cancel", admin.username, f"Cancelled leave request #{leave_request.id}")
    db.commit()

    return RedirectResponse("/leave-requests", status_code=status.HTTP_303_SEE_OTHER)
