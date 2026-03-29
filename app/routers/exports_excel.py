
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, extract
from sqlalchemy.orm import Session, joinedload
from io import BytesIO
from openpyxl import Workbook

from app.dependencies import get_db, get_current_admin
from app.models import LeaveRequest

router = APIRouter(prefix="/exports", tags=["exports"])

@router.get("/payroll-excel")
def export_payroll_excel(
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

    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll Leave"

    ws.append(["Employee", "Leave Type", "Date From", "Date To", "Days"])

    for r in rows:
        ws.append([
            r.employee.full_name if r.employee else "",
            r.leave_type.name if r.leave_type else "",
            str(r.date_from),
            str(r.date_to),
            r.days_requested,
        ])

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"payroll_leave_{year}_{month}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
