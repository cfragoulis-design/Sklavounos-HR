from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Employee, LeaveRequest


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
