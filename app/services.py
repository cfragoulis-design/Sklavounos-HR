from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import AuditLog, Employee, LeaveBalance, LeaveRequest, LeaveType


DEFAULT_EMPLOYEE_LOCATIONS = ["Central", "Workshop", "Shop"]
DEFAULT_EMPLOYEE_DEPARTMENTS = ["Production", "Retail", "Logistics", "Admin"]

# Σταθερές αργίες Ελλάδας που ΔΕΝ μετράνε στην άδεια.
# Εξαιρούνται επίσης όλες οι Κυριακές.
# Το Αγίου Πνεύματος ΔΕΝ εξαιρείται για τη δική σας περίπτωση.
GREEK_FIXED_HOLIDAYS = {
    "01-01",  # Πρωτοχρονιά
    "06-01",  # Θεοφάνια
    "25-03",  # 25η Μαρτίου
    "01-05",  # Πρωτομαγιά
    "15-08",  # Δεκαπενταύγουστος
    "28-10",  # 28η Οκτωβρίου
    "25-12",  # Χριστούγεννα
    "26-12",  # Σύναξη Θεοτόκου
}


def get_dashboard_stats(db: Session) -> dict:
    total_employees = db.scalar(
        select(func.count()).select_from(Employee).where(Employee.is_active.is_(True))
    ) or 0

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

    absences_today = (
        db.execute(
            select(LeaveRequest)
            .options(joinedload(LeaveRequest.employee), joinedload(LeaveRequest.leave_type))
            .where(
                LeaveRequest.status == "approved",
                LeaveRequest.date_from <= date.today(),
                LeaveRequest.date_to >= date.today(),
            )
            .order_by(LeaveRequest.date_to.asc(), LeaveRequest.date_from.asc())
        )
        .scalars()
        .all()
    )

    return {
        "total_employees": total_employees,
        "pending_requests": pending_requests,
        "todays_absences": todays_absences,
        "upcoming_leaves": upcoming_leaves,
        "absences_today": absences_today,
    }


def write_audit_log(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: str | None,
    details: str | None = None,
) -> None:
    db.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            details=details,
        )
    )


def get_employee_locations() -> list[str]:
    return DEFAULT_EMPLOYEE_LOCATIONS


def get_employee_departments() -> list[str]:
    return DEFAULT_EMPLOYEE_DEPARTMENTS


def calculate_days_requested(date_from: date, date_to: date) -> int:
    days = 0
    current = date_from

    while current <= date_to:
        # Κυριακή
        if current.weekday() == 6:
            current += timedelta(days=1)
            continue

        # Σταθερή αργία
        if current.strftime("%m-%d") in GREEK_FIXED_HOLIDAYS:
            current += timedelta(days=1)
            continue

        days += 1
        current += timedelta(days=1)

    return max(days, 0)


def get_or_create_leave_balance(db: Session, employee: Employee, year: int) -> LeaveBalance:
    balance = db.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee.id,
            LeaveBalance.year == year,
        )
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
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.year == year,
        )
    )
    if not balance:
        return None

    return {
        "year": year,
        "entitled_days": balance.entitled_days,
        "used_days": balance.used_days,
        "remaining_days": balance.remaining_days,
    }


def get_active_leave_types(db: Session) -> list[LeaveType]:
    return (
        db.execute(
            select(LeaveType)
            .where(LeaveType.is_active.is_(True))
            .order_by(LeaveType.name.asc())
        )
        .scalars()
        .all()
    )


def get_leave_request_with_relations(db: Session, request_id: int) -> LeaveRequest | None:
    return db.scalar(
        select(LeaveRequest)
        .options(joinedload(LeaveRequest.employee), joinedload(LeaveRequest.leave_type))
        .where(LeaveRequest.id == request_id)
    )
