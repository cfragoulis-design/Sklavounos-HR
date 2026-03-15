from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import SESSION_KEY, authenticate_admin
from app.dependencies import get_db

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
def login_page(request: Request):
    if request.session.get(SESSION_KEY):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = authenticate_admin(db, username=username.strip(), password=password)
    if not admin:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Λάθος username ή password."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    request.session[SESSION_KEY] = admin.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
