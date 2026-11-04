from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.products.importer import COLUMN_DEFINITIONS

TEMPLATE_SHEET = "产品导入"
GUIDE_SHEET = "填写说明"
_COLUMN_WIDTHS = {
    "product_code": 22,
    "product_name": 32,
    "category": 14,
    "standard_code": 16,
    "material": 14,
    "grade": 12,
    "diameter": 12,
    "length": 12,
    "thread_pitch": 12,
    "head_type": 14,
    "drive_type": 14,
    "surface_finish": 16,
    "sales_unit": 12,
    "moq": 12,
}
_HEADER_FILL = PatternFill("solid", fgColor="2F5597")
_HEADER_FONT = Font(bold=True, color="FFFFFF")


def render_import_template() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = TEMPLATE_SHEET

    for index, (field, header, _) in enumerate(COLUMN_DEFINITIONS, start=1):
        cell = sheet.cell(row=1, column=index, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.column_dimensions[get_column_letter(index)].width = _COLUMN_WIDTHS.get(field, 16)
    sheet.freeze_panes = "A2"

    guide = workbook.create_sheet(GUIDE_SHEET)
    guide.append(["字段", "说明"])
    for cell in guide[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
    for _, header, note in COLUMN_DEFINITIONS:
        guide.append([header, note])
    guide.column_dimensions["A"].width = 18
    guide.column_dimensions["B"].width = 60

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


__all__ = ["render_import_template"]
