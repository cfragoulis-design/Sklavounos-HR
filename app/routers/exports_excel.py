from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, extract
from sqlalchemy.orm import Session, joinedload
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.table import Table, TableStyleInfo

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

    headers = ["Employee", "Leave Type", "Date From", "Date To", "Days"]
    ws.append(headers)

    center = Alignment(horizontal="center", vertical="center")

    # Header style
    for col in range(1, 6):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.alignment = center

    row_idx = 2
    for r in rows:
        ws.cell(row=row_idx, column=1, value=r.employee.full_name if r.employee else "")
        ws.cell(row=row_idx, column=2, value=r.leave_type.name if r.leave_type else "")
        ws.cell(row=row_idx, column=3, value=r.date_from)
        ws.cell(row=row_idx, column=4, value=r.date_to)

        # Formula for Days
        ws.cell(row=row_idx, column=5, value=f'=IF(AND(C{row_idx}<>"",D{row_idx}<>""),D{row_idx}-C{row_idx}+1,"")')

        for col in range(1, 6):
            ws.cell(row=row_idx, column=col).alignment = center

        row_idx += 1

    # Table styling
    if row_idx > 2:
        table = Table(displayName="PayrollTable", ref=f"A1:E{row_idx-1}")
        style = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        table.tableStyleInfo = style
        ws.add_table(table)

    # Auto width
    for col in ws.columns:
        max_length = 0
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max_length + 2

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"payroll_leave_{year}_{month}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
