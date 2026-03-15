from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser, LeaveType
from app.services import write_audit_log

router = APIRouter(prefix="/leave-types", tags=["leave-types"])
templates = Jinja2Templates(directory="app/templates")


def _render_form(request: Request, admin: AdminUser, leave_type: LeaveType | None, error: str | None = None):
    return templates.TemplateResponse(
        "leave_type_form.html",
        {
            "request": request,
            "admin": admin,
            "leave_type": leave_type,
            "error": error,
            "page_title": "Νέος τύπος άδειας" if leave_type is None else f"Επεξεργασία: {leave_type.name}",
            "active_page": "leave-types",
        },
        status_code=status.HTTP_400_BAD_REQUEST if error else status.HTTP_200_OK,
    )


@router.get("")
def leave_types_list(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    leave_types = db.execute(select(LeaveType).order_by(LeaveType.name.asc())).scalars().all()
    return templates.TemplateResponse(
        "leave_types.html",
        {
            "request": request,
            "admin": admin,
            "leave_types": leave_types,
            "page_title": "Τύποι Αδειών",
            "active_page": "leave-types",
        },
    )


@router.get("/new")
def leave_type_new(request: Request, admin: AdminUser = Depends(get_current_admin)):
    return _render_form(request, admin, None)


@router.post("/new")
def leave_type_create(
    request: Request,
    code: str = Form(""),
    name: str = Form(...),
    counts_against_balance: str | None = Form(None),
    color: str = Form("#2563eb"),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    clean_name = name.strip()
    clean_code = code.strip().upper() or clean_name.upper().replace(" ", "_")

    if not clean_name:
        return _render_form(request, admin, None, error="Το όνομα είναι υποχρεωτικό.")

    exists = db.scalar(select(LeaveType).where(LeaveType.code == clean_code))
    if exists:
        return _render_form(request, admin, None, error="Υπάρχει ήδη τύπος άδειας με αυτό το code.")

    leave_type = LeaveType(
        code=clean_code,
        name=clean_name,
        counts_against_balance=bool(counts_against_balance),
        color=(color or "#2563eb").strip(),
        is_active=True if is_active is None else bool(is_active),
    )
    db.add(leave_type)
    db.commit()
    db.refresh(leave_type)

    write_audit_log(db, "leave_type", leave_type.id, "create", admin.username, f"Created leave type {leave_type.name}")
    db.commit()

    return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{leave_type_id}/edit")
def leave_type_edit(
    leave_type_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    leave_type = db.get(LeaveType, leave_type_id)
    if not leave_type:
        return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)
    return _render_form(request, admin, leave_type)


@router.post("/{leave_type_id}/edit")
def leave_type_update(
    leave_type_id: int,
    request: Request,
    code: str = Form(""),
    name: str = Form(...),
    counts_against_balance: str | None = Form(None),
    color: str = Form("#2563eb"),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    leave_type = db.get(LeaveType, leave_type_id)
    if not leave_type:
        return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)

    clean_name = name.strip()
    clean_code = code.strip().upper() or clean_name.upper().replace(" ", "_")

    if not clean_name:
        return _render_form(request, admin, leave_type, error="Το όνομα είναι υποχρεωτικό.")

    duplicate = db.scalar(select(LeaveType).where(LeaveType.code == clean_code, LeaveType.id != leave_type.id))
    if duplicate:
        return _render_form(request, admin, leave_type, error="Υπάρχει ήδη τύπος άδειας με αυτό το code.")

    leave_type.code = clean_code
    leave_type.name = clean_name
    leave_type.counts_against_balance = bool(counts_against_balance)
    leave_type.color = (color or "#2563eb").strip()
    leave_type.is_active = True if is_active is None else bool(is_active)

    db.commit()
    write_audit_log(db, "leave_type", leave_type.id, "update", admin.username, f"Updated leave type {leave_type.name}")
    db.commit()

    return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{leave_type_id}/toggle-active")
def leave_type_toggle_active(
    leave_type_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    leave_type = db.get(LeaveType, leave_type_id)
    if not leave_type:
        return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)

    leave_type.is_active = not leave_type.is_active
    db.commit()

    action = "activate" if leave_type.is_active else "deactivate"
    write_audit_log(db, "leave_type", leave_type.id, action, admin.username, f"Toggled active={leave_type.is_active}")
    db.commit()

    return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)
