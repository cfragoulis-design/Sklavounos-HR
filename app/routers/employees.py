from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models import AdminUser, Employee

router = APIRouter(prefix="/employees", tags=["employees"])
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def employees_list(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    employees = db.execute(select(Employee).order_by(Employee.full_name.asc())).scalars().all()
    return templates.TemplateResponse(
        "employees.html",
        {
            "request": request,
            "admin": admin,
            "employees": employees,
            "page_title": "Εργαζόμενοι",
            "active_page": "employees",
        },
    )


@router.get("/new")
def employee_new(request: Request, admin: AdminUser = Depends(get_current_admin)):
    return templates.TemplateResponse(
        "placeholder.html",
        {
            "request": request,
            "admin": admin,
            "page_title": "Νέος εργαζόμενος",
            "active_page": "employees",
            "title": "Νέος εργαζόμενος",
            "message": "Το create/edit employee form θα μπει στο επόμενο patch.",
        },
    )
