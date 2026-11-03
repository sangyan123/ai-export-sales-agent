from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.quote import Quote, QuoteItem

_PDF_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(_PDF_FONT))


def _amount(value: Any, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}"


def _terms(quote: Quote) -> dict[str, Any]:
    return dict(quote.terms_json or {})


def render_quote_pdf(
    *,
    quote: Quote,
    items: list[QuoteItem],
    customer_name: str | None = None,
) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Quotation {quote.quote_no}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "QuoteTitle",
        parent=styles["Title"],
        fontName=_PDF_FONT,
        fontSize=18,
        leading=24,
    )
    body_style = ParagraphStyle(
        "QuoteBody",
        parent=styles["Normal"],
        fontName=_PDF_FONT,
        fontSize=9,
        leading=13,
    )

    story: list[Any] = [
        Paragraph("QUOTATION", title_style),
        Spacer(1, 6 * mm),
    ]
    meta_rows = [
        ["Quote No.", quote.quote_no, "Version", str(quote.version_no)],
        [
            "Status",
            quote.status,
            "Currency",
            quote.currency,
        ],
        [
            "Valid Until",
            quote.valid_until.isoformat() if quote.valid_until else "-",
            "Customer",
            customer_name or "-",
        ],
    ]
    meta_table = Table(meta_rows, colWidths=[28 * mm, 55 * mm, 28 * mm, 55 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _PDF_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#555555")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([meta_table, Spacer(1, 6 * mm)])

    header = ["#", "Product Code", "Description", "Qty", "Unit", "Unit Price", "Amount"]
    rows: list[list[str]] = [header]
    for item in items:
        snapshot = item.product_snapshot_json or {}
        rows.append(
            [
                str(item.line_no),
                str(snapshot.get("product_code") or "-"),
                str(snapshot.get("product_name") or "-"),
                _amount(item.quantity, 4),
                item.unit,
                _amount(item.unit_price_display),
                _amount(item.line_total_display),
            ]
        )
    item_table = Table(
        rows,
        colWidths=[10 * mm, 30 * mm, 55 * mm, 22 * mm, 15 * mm, 27 * mm, 30 * mm],
        repeatRows=1,
    )
    item_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _PDF_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B7C3")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F9")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([item_table, Spacer(1, 5 * mm)])

    totals = [
        ["Subtotal", _amount(quote.subtotal_display)],
        ["Discount", _amount(quote.discount_total_display)],
        ["Freight", _amount(quote.freight_total_display)],
        ["Other Charges", _amount(quote.other_charges_display)],
        ["Grand Total", f"{_amount(quote.grand_total_display)} {quote.currency}"],
    ]
    totals_table = Table(totals, colWidths=[45 * mm, 40 * mm], hAlign="RIGHT")
    totals_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _PDF_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, 0), (-1, 0), 0.4, colors.HexColor("#B0B7C3")),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#1F3A5F")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.extend([totals_table, Spacer(1, 6 * mm)])

    terms = _terms(quote)
    if terms:
        story.append(Paragraph("Terms &amp; Conditions", body_style))
        term_rows = [[str(key), str(value)] for key, value in terms.items()]
        terms_table = Table(term_rows, colWidths=[35 * mm, 120 * mm])
        terms_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), _PDF_FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.extend([Spacer(1, 2 * mm), terms_table])

    document.build(story)
    return buffer.getvalue()


def render_quote_xlsx(
    *,
    quote: Quote,
    items: list[QuoteItem],
    customer_name: str | None = None,
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quotation"

    column_widths = [5, 20, 40, 14, 8, 14, 16]
    for index, width in enumerate(column_widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    title_font = Font(name="Calibri", size=16, bold=True, color="1F3A5F")
    label_font = Font(name="Calibri", size=10, color="555555")
    value_font = Font(name="Calibri", size=10)
    header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F3A5F")
    thin = Side(style="thin", color="B0B7C3")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    sheet.merge_cells("A1:G1")
    sheet["A1"] = "QUOTATION"
    sheet["A1"].font = title_font
    sheet["A1"].alignment = Alignment(horizontal="center")

    meta_rows = [
        ("Quote No.", quote.quote_no, "Version", str(quote.version_no)),
        ("Status", quote.status, "Currency", quote.currency),
        (
            "Valid Until",
            quote.valid_until.isoformat() if quote.valid_until else "-",
            "Customer",
            customer_name or "-",
        ),
    ]
    row_index = 3
    for left_label, left_value, right_label, right_value in meta_rows:
        sheet.cell(row=row_index, column=1, value=left_label).font = label_font
        sheet.cell(row=row_index, column=2, value=left_value).font = value_font
        sheet.cell(row=row_index, column=4, value=right_label).font = label_font
        sheet.cell(row=row_index, column=5, value=right_value).font = value_font
        row_index += 1

    header_row = row_index + 1
    headers = ["#", "Product Code", "Description", "Qty", "Unit", "Unit Price", "Amount"]
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=header_row, column=column, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    row_index = header_row + 1
    for item in items:
        snapshot = item.product_snapshot_json or {}
        values = [
            item.line_no,
            snapshot.get("product_code") or "-",
            snapshot.get("product_name") or "-",
            float(item.quantity),
            item.unit,
            float(item.unit_price_display),
            float(item.line_total_display),
        ]
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=column, value=value)
            cell.border = border
            if column == 4:
                cell.number_format = "#,##0.0000"
            if column in (6, 7):
                cell.number_format = "#,##0.00"
        row_index += 1

    row_index += 1
    totals = [
        ("Subtotal", quote.subtotal_display),
        ("Discount", quote.discount_total_display),
        ("Freight", quote.freight_total_display),
        ("Other Charges", quote.other_charges_display),
        ("Grand Total", quote.grand_total_display),
    ]
    for label, value in totals:
        label_cell = sheet.cell(row=row_index, column=5, value=label)
        label_cell.font = label_font
        value_cell = sheet.cell(row=row_index, column=7, value=float(value))
        value_cell.number_format = "#,##0.00"
        value_cell.font = value_font
        row_index += 1
    sheet.cell(row=row_index - 1, column=5).font = Font(name="Calibri", size=10, bold=True)
    sheet.cell(row=row_index - 1, column=7).font = Font(name="Calibri", size=10, bold=True)
    currency_cell = sheet.cell(row=row_index - 1, column=8, value=quote.currency)
    currency_cell.font = value_font

    terms = _terms(quote)
    if terms:
        row_index += 1
        sheet.cell(row=row_index, column=1, value="Terms & Conditions").font = Font(
            name="Calibri", size=10, bold=True
        )
        row_index += 1
        for key, value in terms.items():
            sheet.cell(row=row_index, column=1, value=str(key)).font = label_font
            sheet.cell(row=row_index, column=2, value=str(value)).font = value_font
            row_index += 1

    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
