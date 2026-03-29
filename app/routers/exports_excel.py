from io import BytesIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from sqlalchemy import extract, select
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_current_admin, get_db
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
        .order_by(LeaveRequest.date_from.asc(), LeaveRequest.id.asc())
    )

    rows = db.execute(stmt).scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll Leave"

    headers = ["Employee", "Leave Type", "Date From", "Date To", "Days"]
    ws.append(headers)

    center = Alignment(horizontal="center", vertical="center")
    header_fill = PatternFill(fill_type="solid", fgColor="D9E2F3")
    header_font = Font(bold=True)
    thin_side = Side(style="thin", color="D9D9D9")
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.alignment = center
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    row_idx = 2
    for request in rows:
        ws.cell(row=row_idx, column=1, value=request.employee.full_name if request.employee else "")
        ws.cell(row=row_idx, column=2, value=request.leave_type.name if request.leave_type else "")
        ws.cell(row=row_idx, column=3, value=request.date_from)
        ws.cell(row=row_idx, column=4, value=request.date_to)
        ws.cell(
            row=row_idx,
            column=5,
            value=f'=IF(AND(C{row_idx}<>"",D{row_idx}<>""),D{row_idx}-C{row_idx}+1,"")',
        )

        for col in range(1, 6):
            cell = ws.cell(row=row_idx, column=col)
            cell.alignment = center
            cell.border = thin_border
            if col in (3, 4):
                cell.number_format = "dd/mm/yyyy"

        row_idx += 1

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:E{max(row_idx - 1, 1)}"

    if row_idx > 2:
        table = Table(displayName="PayrollLeaveTable", ref=f"A1:E{row_idx - 1}")
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(table)

    column_widths = {
        "A": 28,
        "B": 20,
        "C": 14,
        "D": 14,
        "E": 10,
    }
    for col_letter, width in column_widths.items():
        ws.column_dimensions[col_letter].width = width

    for row in range(2, max(row_idx, 3)):
        ws.row_dimensions[row].height = 22

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"payroll_leave_{year}_{month}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
