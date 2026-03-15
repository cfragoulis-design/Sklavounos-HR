from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser, Employee
from app.services import get_employee_locations, get_employee_departments, write_audit_log

router = APIRouter(prefix="/employees", tags=["employees"])
templates = Jinja2Templates(directory="app/templates")


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_hire_date(value: str | None):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _render_form(
    request: Request,
    admin: AdminUser,
    employee: Employee | None,
    error: str | None = None,
    form_data: dict | None = None,
):
    return templates.TemplateResponse(
        "employee_form.html",
        {
            "request": request,
            "admin": admin,
            "employee": employee,
            "error": error,
            "form_data": form_data or {},
            "locations": get_employee_locations(),
            "departments": get_employee_departments(),
            "page_title": "Νέος εργαζόμενος" if employee is None else f"Επεξεργασία: {employee.full_name}",
            "active_page": "employees",
        },
        status_code=status.HTTP_400_BAD_REQUEST if error else status.HTTP_200_OK,
    )


@router.get("")
def employees_list(
    request: Request,
    q: str = "",
    status_filter: str = "all",
    created: int = 0,
    updated: int = 0,
    toggled: int = 0,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    stmt = select(Employee)
    search = q.strip()

    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Employee.full_name.ilike(like),
                Employee.phone.ilike(like),
                Employee.role_title.ilike(like),
                Employee.department.ilike(like),
                Employee.location.ilike(like),
            )
        )

    if status_filter == "active":
        stmt = stmt.where(Employee.is_active.is_(True))
    elif status_filter == "inactive":
        stmt = stmt.where(Employee.is_active.is_(False))

    employees = db.execute(stmt.order_by(Employee.full_name.asc())).scalars().all()

    flash_message = None
    if created:
        flash_message = "Ο εργαζόμενος αποθηκεύτηκε κανονικά."
    elif updated:
        flash_message = "Οι αλλαγές αποθηκεύτηκαν."
    elif toggled:
        flash_message = "Η κατάσταση του εργαζομένου ενημερώθηκε."

    return templates.TemplateResponse(
        "employees.html",
        {
            "request": request,
            "admin": admin,
            "employees": employees,
            "page_title": "Εργαζόμενοι",
            "active_page": "employees",
            "q": search,
            "status_filter": status_filter,
            "flash_message": flash_message,
            "employees_count": len(employees),
        },
    )


@router.get("/new")
def employee_new(request: Request, admin: AdminUser = Depends(get_current_admin)):
    return _render_form(request=request, admin=admin, employee=None)


@router.post("/new")
def employee_create(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(""),
    role_title: str = Form(""),
    department: str = Form(""),
    location: str = Form(""),
    hire_date: str = Form(""),
    annual_leave_days: int = Form(20),
    notes: str = Form(""),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    form_data = {
        "full_name": full_name,
        "phone": phone,
        "role_title": role_title,
        "department": department,
        "location": location,
        "hire_date": hire_date,
        "annual_leave_days": annual_leave_days,
        "notes": notes,
        "is_active": True if is_active is None else bool(is_active),
    }

    clean_name = full_name.strip()
    if not clean_name:
        return _render_form(request, admin, None, error="Το ονοματεπώνυμο είναι υποχρεωτικό.", form_data=form_data)
    if annual_leave_days < 0:
        return _render_form(request, admin, None, error="Οι ημέρες άδειας δεν μπορεί να είναι αρνητικές.", form_data=form_data)

    try:
        parsed_hire_date = _parse_hire_date(hire_date)
    except ValueError:
        return _render_form(request, admin, None, error="Μη έγκυρη ημερομηνία πρόσληψης.", form_data=form_data)

    employee = Employee(
        full_name=clean_name,
        phone=_clean_optional(phone),
        role_title=_clean_optional(role_title),
        department=_clean_optional(department),
        location=_clean_optional(location),
        hire_date=parsed_hire_date,
        annual_leave_days=annual_leave_days,
        notes=_clean_optional(notes),
        is_active=True if is_active is None else bool(is_active),
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    write_audit_log(db, "employee", employee.id, "create", admin.username, f"Created employee {employee.full_name}")
    db.commit()

    return RedirectResponse(url="/employees?created=1&status_filter=all", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{employee_id}/edit")
def employee_edit(
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)
    return _render_form(request=request, admin=admin, employee=employee)


@router.post("/{employee_id}/edit")
def employee_update(
    employee_id: int,
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(""),
    role_title: str = Form(""),
    department: str = Form(""),
    location: str = Form(""),
    hire_date: str = Form(""),
    annual_leave_days: int = Form(20),
    notes: str = Form(""),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)

    form_data = {
        "full_name": full_name,
        "phone": phone,
        "role_title": role_title,
        "department": department,
        "location": location,
        "hire_date": hire_date,
        "annual_leave_days": annual_leave_days,
        "notes": notes,
        "is_active": bool(is_active),
    }

    clean_name = full_name.strip()
    if not clean_name:
        return _render_form(request, admin, employee, error="Το ονοματεπώνυμο είναι υποχρεωτικό.", form_data=form_data)
    if annual_leave_days < 0:
        return _render_form(request, admin, employee, error="Οι ημέρες άδειας δεν μπορεί να είναι αρνητικές.", form_data=form_data)

    try:
        parsed_hire_date = _parse_hire_date(hire_date)
    except ValueError:
        return _render_form(request, admin, employee, error="Μη έγκυρη ημερομηνία πρόσληψης.", form_data=form_data)

    employee.full_name = clean_name
    employee.phone = _clean_optional(phone)
    employee.role_title = _clean_optional(role_title)
    employee.department = _clean_optional(department)
    employee.location = _clean_optional(location)
    employee.hire_date = parsed_hire_date
    employee.annual_leave_days = annual_leave_days
    employee.notes = _clean_optional(notes)
    employee.is_active = bool(is_active)

    db.commit()
    write_audit_log(db, "employee", employee.id, "update", admin.username, f"Updated employee {employee.full_name}")
    db.commit()

    return RedirectResponse(url="/employees?updated=1&status_filter=all", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{employee_id}/toggle-active")
def employee_toggle_active(
    employee_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)

    employee.is_active = not employee.is_active
    db.commit()

    action = "activate" if employee.is_active else "deactivate"
    write_audit_log(db, "employee", employee.id, action, admin.username, f"Toggled active={employee.is_active}")
    db.commit()

    return RedirectResponse(url="/employees?toggled=1&status_filter=all", status_code=status.HTTP_303_SEE_OTHER)
