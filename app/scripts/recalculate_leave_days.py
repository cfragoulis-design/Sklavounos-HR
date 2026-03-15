
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.database import SessionLocal
from app.models import LeaveRequest
from app.services import calculate_days_requested


def recalculate_all_leave_days():
    db: Session = SessionLocal()
    try:
        requests = db.execute(select(LeaveRequest)).scalars().all()

        updated = 0

        for r in requests:
            new_days = calculate_days_requested(r.date_from, r.date_to)

            if r.days_requested != new_days:
                r.days_requested = new_days
                updated += 1

        db.commit()

        print(f"Recalculated leave days. Updated records: {updated}")
    finally:
        db.close()


if __name__ == "__main__":
    recalculate_all_leave_days()
