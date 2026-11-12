"""Builds a finished Excel workbook: styled header, sensible column widths, frozen header row."""
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def build(book, path):
    """book: {'sheets': [{'name', 'columns': [...], 'rows': [[...]]}]}. Cells starting with '=' are formulas."""
    wb = Workbook()
    wb.remove(wb.active)
    for sh in book.get("sheets", [])[:8] or [{"name": "Sheet1", "columns": [], "rows": []}]:
        ws = wb.create_sheet(str(sh.get("name", "Sheet"))[:31])
        cols = [str(c) for c in sh.get("columns", [])]
        if cols:
            ws.append(cols)
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="1B2A41")
                c.alignment = Alignment(vertical="center")
            ws.freeze_panes = "A2"
        for row in sh.get("rows", [])[:2000]:
            ws.append([_num(v) for v in row])
        for i in range(1, max(len(cols), max((len(r) for r in sh.get("rows", [])), default=0)) + 1):
            width = max([len(str(ws.cell(r, i).value or "")) for r in range(1, min(ws.max_row, 200) + 1)] + [8])
            ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)
    wb.save(path)
    return len(wb.sheetnames)


def _num(v):
    if isinstance(v, str) and not v.startswith("="):
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            return v
    return v


def check(path):
    wb = load_workbook(path)
    return {"sheets": wb.sheetnames, "rows": sum(ws.max_row for ws in wb.worksheets)}
