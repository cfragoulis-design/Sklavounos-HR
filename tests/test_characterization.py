from __future__ import annotations

import os
import hashlib
import subprocess
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

TEST_DATABASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "test-results"
    / "hr-characterization.sqlite3"
)
TEST_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
TEST_DATABASE_PATH.unlink(missing_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "characterization-only-secret"
os.environ["ADMIN_USER"] = "characterization-admin"
os.environ["ADMIN_PASSWORD"] = "characterization-password"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app, seed_defaults  # noqa: E402
from app.models import AuditLog, Employee, LeaveBalance, LeaveRequest, LeaveType  # noqa: E402
from app.services import calculate_days_requested  # noqa: E402


EXPECTED_RUNTIME_ROUTES = {
    ("GET", "/"),
    ("GET", "/debug/seed-sample"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/employees"),
    ("GET", "/employees/new"),
    ("GET", "/employees/{employee_id}/balance-adjustment"),
    ("GET", "/employees/{employee_id}/edit"),
    ("GET", "/exports/payroll-excel"),
    ("GET", "/favicon.ico"),
    ("GET", "/health"),
    ("GET", "/leave-calendar"),
    ("GET", "/leave-requests"),
    ("GET", "/leave-requests/new"),
    ("GET", "/leave-types"),
    ("GET", "/leave-types/new"),
    ("GET", "/leave-types/{leave_type_id}/edit"),
    ("GET", "/login"),
    ("GET", "/logout"),
    ("GET", "/openapi.json"),
    ("GET", "/redoc"),
    ("GET", "/session-check"),
    ("POST", "/employees/new"),
    ("POST", "/employees/{employee_id}/balance-adjustment"),
    ("POST", "/employees/{employee_id}/edit"),
    ("POST", "/employees/{employee_id}/toggle-active"),
    ("POST", "/leave-requests/new"),
    ("POST", "/leave-requests/{request_id}/approve"),
    ("POST", "/leave-requests/{request_id}/cancel"),
    ("POST", "/leave-requests/{request_id}/reject"),
    ("POST", "/leave-types/new"),
    ("POST", "/leave-types/{leave_type_id}/edit"),
    ("POST", "/leave-types/{leave_type_id}/toggle-active"),
    ("POST", "/login"),
}
EXPECTED_LEGACY_RUNTIME_FILE_COUNT = 39
EXPECTED_LEGACY_RUNTIME_SHA256 = (
    "fcc339b5473cbd6483aa4d678fa52b3977502ce669efe67245e41b5d517baf88"
)


@pytest.fixture(scope="session", autouse=True)
def _remove_disposable_database() -> Iterator[None]:
    yield
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_defaults()
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={
            "username": "characterization-admin",
            "password": "characterization-password",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def _create_employee(client: TestClient) -> Employee:
    response = client.post(
        "/employees/new",
        data={
            "full_name": "Characterization Employee",
            "phone": "6900000000",
            "role_title": "Operator",
            "department": "Production",
            "location": "Central",
            "hire_date": "2026-01-02",
            "annual_leave_days": "20",
            "notes": "Disposable characterization row",
            "is_active": "on",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/employees?created=1&status_filter=all"
    with SessionLocal() as session:
        employee = session.scalar(
            select(Employee).where(
                Employee.full_name == "Characterization Employee"
            )
        )
        assert employee is not None
        session.expunge(employee)
        return employee


def test_runtime_route_inventory_is_frozen() -> None:
    actual = {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
        if method not in {"HEAD", "OPTIONS"}
    }
    assert actual == EXPECTED_RUNTIME_ROUTES


def test_legacy_runtime_source_manifest_is_frozen() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    tracked_files = sorted(
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "--",
                "app",
                "requirements.txt",
                "Procfile",
                "railway.json",
            ],
            cwd=repository_root,
            text=True,
        ).splitlines()
    )
    digest = hashlib.sha256()
    for relative_path in tracked_files:
        digest.update(relative_path.replace("\\", "/").encode())
        digest.update(b"\0")
        digest.update((repository_root / relative_path).read_bytes())
        digest.update(b"\0")

    assert len(tracked_files) == EXPECTED_LEGACY_RUNTIME_FILE_COUNT
    assert digest.hexdigest() == EXPECTED_LEGACY_RUNTIME_SHA256


def test_public_and_admin_only_boundaries_are_characterized(
    client: TestClient,
) -> None:
    assert client.get("/health").json() == {"ok": True, "app": "Sklavounos HR"}
    assert client.get("/session-check").json() == {"authenticated": False}

    for path in (
        "/",
        "/employees",
        "/leave-requests",
        "/leave-types",
        "/leave-calendar",
        "/exports/payroll-excel",
    ):
        response = client.get(path)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    debug_seed = client.get("/debug/seed-sample")
    assert debug_seed.status_code == 200
    assert debug_seed.json() == {"ok": True}
    with SessionLocal() as session:
        assert session.scalar(select(Employee.id)) is not None


def test_admin_employee_leave_balance_and_audit_flow(
    client: TestClient,
) -> None:
    rejected_login = client.post(
        "/login",
        data={"username": "characterization-admin", "password": "wrong"},
    )
    assert rejected_login.status_code == 400
    assert client.get("/session-check").json() == {"authenticated": False}

    _login(client)
    assert client.get("/session-check").json() == {"authenticated": True}
    employee = _create_employee(client)

    with SessionLocal() as session:
        annual_leave = session.scalar(
            select(LeaveType).where(LeaveType.code == "ANNUAL")
        )
        assert annual_leave is not None
        annual_leave_id = annual_leave.id

    create_leave = client.post(
        "/leave-requests/new",
        data={
            "employee_id": str(employee.id),
            "leave_type_id": str(annual_leave_id),
            "date_from": "2026-02-02",
            "date_to": "2026-02-04",
            "note": "Characterization leave",
        },
    )
    assert create_leave.status_code == 303
    assert create_leave.headers["location"] == "/leave-requests"

    with SessionLocal() as session:
        leave_request = session.scalar(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == employee.id
            )
        )
        assert leave_request is not None
        assert leave_request.status == "pending"
        assert leave_request.days_requested == 3
        request_id = leave_request.id

    approve = client.post(f"/leave-requests/{request_id}/approve")
    assert approve.status_code == 303
    with SessionLocal() as session:
        leave_request = session.get(LeaveRequest, request_id)
        balance = session.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee.id,
                LeaveBalance.year == 2026,
            )
        )
        assert leave_request is not None
        assert leave_request.status == "approved"
        assert leave_request.approved_by == "characterization-admin"
        assert balance is not None
        assert (
            balance.entitled_days,
            balance.used_days,
            balance.remaining_days,
        ) == (20, 3, 17)

    cancel = client.post(f"/leave-requests/{request_id}/cancel")
    assert cancel.status_code == 303
    with SessionLocal() as session:
        leave_request = session.get(LeaveRequest, request_id)
        balance = session.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee.id,
                LeaveBalance.year == 2026,
            )
        )
        actions = list(
            session.scalars(
                select(AuditLog.action).order_by(AuditLog.id)
            ).all()
        )
        assert leave_request is not None
        assert leave_request.status == "cancelled"
        assert balance is not None
        # Current legacy behavior: cancellation commits after recalculation queried
        # the still-approved row, so the persisted balance remains stale.
        assert (balance.used_days, balance.remaining_days) == (3, 17)
        assert actions == ["create", "create", "approve", "cancel"]

    logout = client.get("/logout")
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
    assert client.get("/session-check").json() == {"authenticated": False}


def test_existing_validation_and_day_counting_rules(
    client: TestClient,
) -> None:
    _login(client)
    invalid_employee = client.post(
        "/employees/new",
        data={
            "full_name": "Invalid Balance",
            "annual_leave_days": "-1",
        },
    )
    assert invalid_employee.status_code == 400

    employee = _create_employee(client)
    with SessionLocal() as session:
        annual_leave = session.scalar(
            select(LeaveType).where(LeaveType.code == "ANNUAL")
        )
        assert annual_leave is not None
        annual_leave_id = annual_leave.id

    reversed_dates = client.post(
        "/leave-requests/new",
        data={
            "employee_id": str(employee.id),
            "leave_type_id": str(annual_leave_id),
            "date_from": "2026-02-04",
            "date_to": "2026-02-02",
        },
    )
    assert reversed_dates.status_code == 400
    with SessionLocal() as session:
        assert session.scalar(select(LeaveRequest.id)) is None

    # Current legacy behavior: fixed holidays are stored as DD-MM while the
    # calculator compares MM-DD, so 25 March is counted.
    assert calculate_days_requested(date(2026, 3, 24), date(2026, 3, 26)) == 3
    assert calculate_days_requested(date(2026, 2, 7), date(2026, 2, 9)) == 2
