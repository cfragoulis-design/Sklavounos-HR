from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Employee, LeaveRequest


DEFAULT_EMPLOYEE_LOCATIONS = ["Central", "Workshop", "Shop"]
DEFAULT_EMPLOYEE_DEPARTMENTS = ["Production", "Retail", "Logistics", "Admin"]


def get_dashboard_stats(db: Session) -> dict:
    total_employees = db.scalar(select(func.count()).select_from(Employee).where(Employee.is_active.is_(True))) or 0
    pending_requests = db.scalar(
        select(func.count()).select_from(LeaveRequest).where(LeaveRequest.status == "pending")
    ) or 0
    todays_absences = db.scalar(
        select(func.count()).select_from(LeaveRequest).where(
            LeaveRequest.status == "approved",
            LeaveRequest.date_from <= date.today(),
            LeaveRequest.date_to >= date.today(),
        )
    ) or 0
    upcoming_leaves = db.scalar(
        select(func.count()).select_from(LeaveRequest).where(
            LeaveRequest.status == "approved",
            LeaveRequest.date_from > date.today(),
            LeaveRequest.date_from <= date.today() + timedelta(days=14),
        )
    ) or 0

    return {
        "total_employees": total_employees,
        "pending_requests": pending_requests,
        "todays_absences": todays_absences,
        "upcoming_leaves": upcoming_leaves,
    }


def write_audit_log(db: Session, entity_type: str, entity_id: int, action: str, actor: str | None, details: str | None = None) -> None:
    db.add(AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, actor=actor, details=details))
    db.commit()


def get_employee_locations() -> list[str]:
    return DEFAULT_EMPLOYEE_LOCATIONS


def get_employee_departments() -> list[str]:
    return DEFAULT_EMPLOYEE_DEPARTMENTS
