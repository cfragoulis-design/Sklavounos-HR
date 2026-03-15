
from datetime import date
import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, extract
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_db, get_current_admin
from app.models import LeaveRequest

router = APIRouter(prefix="/exports", tags=["exports"])

@router.get("/payroll")
def export_payroll_csv(
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):

    stmt = (
        select(LeaveRequest)
        .options(joinedload(LeaveRequest.employee), joinedload(LeaveRequest.leave_type))
        .where(
            LeaveRequest.status == "approved",
            extract("year", LeaveRequest.date_from) == year,
            extract("month", LeaveRequest.date_from) == month,
        )
    )

    rows = db.execute(stmt).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow([
        "Employee",
        "Leave Type",
        "Date From",
        "Date To",
        "Days"
    ])

    for r in rows:
        writer.writerow([
            r.employee.full_name if r.employee else "",
            r.leave_type.name if r.leave_type else "",
            r.date_from,
            r.date_to,
            r.days_requested,
        ])

    buffer.seek(0)

    filename = f"payroll_leave_export_{year}_{month}.csv"

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        },
    )
