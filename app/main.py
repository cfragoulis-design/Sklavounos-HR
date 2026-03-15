import os
from datetime import date

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select, text
from starlette.middleware.sessions import SessionMiddleware

from app.auth import SESSION_COOKIE_NAME, SESSION_KEY, seed_admin_user
from app.database import Base, SessionLocal, engine
from app.models import Employee, LeaveBalance, LeaveRequest, LeaveType
from app.routers import auth as auth_router
from app.routers import dashboard, employees, leave_requests, leave_types
from app.routers import leave_calendar
from app.routers import exports_excel

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "Sklavounos HR")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")

app = FastAPI(title=APP_NAME)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE_NAME,
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router.router)
app.include_router(dashboard.router)
app.include_router(employees.router)
app.include_router(leave_types.router)
app.include_router(leave_requests.router)
app.include_router(leave_calendar.router)
app.include_router(exports_excel.router)


def ensure_schema_updates() -> None:
    inspector = inspect(engine)
    if inspector.has_table("employees"):
        columns = {col["name"] for col in inspector.get_columns("employees")}
        if "notes" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE employees ADD COLUMN notes TEXT"))


def seed_defaults() -> None:
    with SessionLocal() as db:
        seed_admin_user(db)

        leave_types_seed = [
            ("ANNUAL", "Κανονική Άδεια", True, "green"),
            ("REPO", "Ρεπό", False, "blue"),
            ("SICK", "Ασθένεια", False, "red"),
            ("UNPAID", "Άνευ Αποδοχών", False, "gray"),
            ("SPECIAL", "Ειδική Άδεια", False, "purple"),
        ]

        existing_codes = set(db.scalars(select(LeaveType.code)).all())
        for code, name, counts, color in leave_types_seed:
            if code not in existing_codes:
                db.add(
                    LeaveType(
                        code=code,
                        name=name,
                        counts_against_balance=counts,
                        color=color,
                        is_active=True,
                    )
                )
        db.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema_updates()
    seed_defaults()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def healthcheck():
    return {"ok": True, "app": APP_NAME}


@app.get("/debug/seed-sample")
def debug_seed_sample():
    with SessionLocal() as db:
        employee = db.execute(select(Employee).where(Employee.full_name == "Δείγμα Εργαζομένου")).scalar_one_or_none()
        if not employee:
            employee = Employee(
                full_name="Δείγμα Εργαζομένου",
                phone="6900000000",
                role_title="Υπάλληλος",
                department="Store",
                location="Central",
                annual_leave_days=20,
                notes="Demo εγγραφή για έλεγχο λίστας.",
                is_active=True,
            )
            db.add(employee)
            db.commit()
            db.refresh(employee)

            db.add(
                LeaveBalance(
                    employee_id=employee.id,
                    year=2026,
                    entitled_days=20,
                    used_days=3,
                    remaining_days=17,
                )
            )
            leave_type = db.execute(select(LeaveType).where(LeaveType.code == "ANNUAL")).scalar_one()
            db.add(
                LeaveRequest(
                    employee_id=employee.id,
                    leave_type_id=leave_type.id,
                    date_from=date(2026, 4, 10),
                    date_to=date(2026, 4, 12),
                    days_requested=3,
                    note="Δοκιμαστικό αίτημα",
                    status="pending",
                )
            )
            db.commit()
    return {"ok": True}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(url="/static/favicon.png", status_code=302)


@app.get("/session-check", include_in_schema=False)
def session_check(request: Request):
    return {"authenticated": bool(request.session.get(SESSION_KEY))}
