from datetime import date, timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Employee, LeaveBalance, LeaveRequest, LeaveType


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


def calculate_days_requested(date_from: date, date_to: date) -> int:
    delta = (date_to - date_from).days + 1
    return max(delta, 1)


def get_or_create_leave_balance(db: Session, employee: Employee, year: int) -> LeaveBalance:
    balance = db.scalar(
        select(LeaveBalance).where(LeaveBalance.employee_id == employee.id, LeaveBalance.year == year)
    )
    if not balance:
        balance = LeaveBalance(
            employee_id=employee.id,
            year=year,
            entitled_days=employee.annual_leave_days or 0,
            used_days=0,
            remaining_days=employee.annual_leave_days or 0,
        )
        db.add(balance)
        db.flush()
    return balance


def recalculate_leave_balance(db: Session, employee_id: int, year: int) -> None:
    employee = db.get(Employee, employee_id)
    if not employee:
        return

    balance = get_or_create_leave_balance(db, employee, year)
    balance.entitled_days = employee.annual_leave_days or 0

    used_days = db.scalar(
        select(func.coalesce(func.sum(LeaveRequest.days_requested), 0))
        .select_from(LeaveRequest)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == "approved",
            LeaveType.counts_against_balance.is_(True),
            func.extract("year", LeaveRequest.date_from) == year,
        )
    ) or 0

    balance.used_days = int(used_days)
    balance.remaining_days = int(balance.entitled_days - balance.used_days)
    db.add(balance)


def recalculate_leave_balances_for_request(db: Session, leave_request: LeaveRequest) -> None:
    years = {leave_request.date_from.year, leave_request.date_to.year}
    for year in years:
        recalculate_leave_balance(db, leave_request.employee_id, year)


def get_employee_balance_summary(db: Session, employee_id: int, year: int) -> dict | None:
    employee = db.get(Employee, employee_id)
    if not employee:
        return None
    recalculate_leave_balance(db, employee_id, year)
    db.flush()
    balance = db.scalar(
        select(LeaveBalance).where(LeaveBalance.employee_id == employee_id, LeaveBalance.year == year)
    )
    if not balance:
        return None
    return {
        "year": year,
        "entitled_days": balance.entitled_days,
        "used_days": balance.used_days,
        "remaining_days": balance.remaining_days,
    }
