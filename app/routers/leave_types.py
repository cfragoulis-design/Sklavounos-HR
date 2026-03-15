from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser, LeaveType

router = APIRouter(prefix="/leave-types", tags=["leave-types"])
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def leave_types_list(
    request: Request,
    q: str = "",
    view: str = "active",
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    stmt = select(LeaveType)

    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(LeaveType.code.ilike(like), LeaveType.name.ilike(like)))

    if view == "active":
        stmt = stmt.where(LeaveType.is_active.is_(True))
    elif view == "inactive":
        stmt = stmt.where(LeaveType.is_active.is_(False))

    leave_types = db.execute(stmt.order_by(LeaveType.name.asc())).scalars().all()

    return templates.TemplateResponse(
        "leave_types.html",
        {
            "request": request,
            "admin": admin,
            "leave_types": leave_types,
            "page_title": "Τύποι αδειών",
            "active_page": "leave_types",
            "q": q,
            "view": view,
        },
    )


@router.get("/new")
def leave_type_new(request: Request, admin: AdminUser = Depends(get_current_admin)):
    return templates.TemplateResponse(
        "leave_type_form.html",
        {
            "request": request,
            "admin": admin,
            "page_title": "Νέος τύπος άδειας",
            "active_page": "leave_types",
            "item": None,
            "error": None,
        },
    )


@router.post("")
def leave_type_create(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    color: str = Form("blue"),
    counts_against_balance: str | None = Form(None),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    code_clean = code.strip().upper()
    name_clean = name.strip()

    if not code_clean or not name_clean:
        return templates.TemplateResponse(
            "leave_type_form.html",
            {
                "request": request,
                "admin": admin,
                "page_title": "Νέος τύπος άδειας",
                "active_page": "leave_types",
                "item": None,
                "error": "Το code και το όνομα είναι υποχρεωτικά.",
            },
            status_code=400,
        )

    exists = db.scalar(select(LeaveType).where(LeaveType.code == code_clean))
    if exists:
        return templates.TemplateResponse(
            "leave_type_form.html",
            {
                "request": request,
                "admin": admin,
                "page_title": "Νέος τύπος άδειας",
                "active_page": "leave_types",
                "item": None,
                "error": "Υπάρχει ήδη τύπος άδειας με αυτό το code.",
            },
            status_code=400,
        )

    item = LeaveType(
        code=code_clean,
        name=name_clean,
        color=(color or "").strip() or "blue",
        counts_against_balance=bool(counts_against_balance),
        is_active=bool(is_active),
    )
    db.add(item)
    db.commit()
    return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{leave_type_id}/edit")
def leave_type_edit(
    leave_type_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    item = db.get(LeaveType, leave_type_id)
    if not item:
        raise HTTPException(status_code=404, detail="Leave type not found")

    return templates.TemplateResponse(
        "leave_type_form.html",
        {
            "request": request,
            "admin": admin,
            "page_title": "Επεξεργασία τύπου άδειας",
            "active_page": "leave_types",
            "item": item,
            "error": None,
        },
    )


@router.post("/{leave_type_id}/edit")
def leave_type_update(
    leave_type_id: int,
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    color: str = Form("blue"),
    counts_against_balance: str | None = Form(None),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    item = db.get(LeaveType, leave_type_id)
    if not item:
        raise HTTPException(status_code=404, detail="Leave type not found")

    code_clean = code.strip().upper()
    name_clean = name.strip()

    duplicate = db.scalar(select(LeaveType).where(LeaveType.code == code_clean, LeaveType.id != leave_type_id))
    if duplicate:
        return templates.TemplateResponse(
            "leave_type_form.html",
            {
                "request": request,
                "admin": admin,
                "page_title": "Επεξεργασία τύπου άδειας",
                "active_page": "leave_types",
                "item": item,
                "error": "Υπάρχει ήδη άλλος τύπος άδειας με αυτό το code.",
            },
            status_code=400,
        )

    item.code = code_clean
    item.name = name_clean
    item.color = (color or "").strip() or "blue"
    item.counts_against_balance = bool(counts_against_balance)
    item.is_active = bool(is_active)
    db.add(item)
    db.commit()
    return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{leave_type_id}/toggle")
def leave_type_toggle(
    leave_type_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    item = db.get(LeaveType, leave_type_id)
    if not item:
        raise HTTPException(status_code=404, detail="Leave type not found")

    item.is_active = not item.is_active
    db.add(item)
    db.commit()
    return RedirectResponse("/leave-types", status_code=status.HTTP_303_SEE_OTHER)
