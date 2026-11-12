"""
reports.py — PDF report generation via ReportLab.
Generates weekly / monthly / yearly offering reports and Excel exports.

Reports follow the layout of the reference xlsx (WEEKLY REPORT):
  Ranking | Itorero | Amaturo yose | Icyacumi (sub-cols) | ... | leader | phone

Also produces an Excel export (openpyxl) matching the same shape.
"""

import os
import io
import json
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether,
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import db
from helpers import get_company_header, get_report_footer, get_base_table_style

# Try register a Unicode font for Kinyarwanda characters
_FONT_OK = False
try:
    pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
    _FONT_OK = True
except Exception:
    pass
BASE_FONT = "DejaVu" if _FONT_OK else "Helvetica"
BOLD_FONT = "DejaVu-Bold" if _FONT_OK else "Helvetica-Bold"


def _fmt_money(v):
    try:
        return f"{int(round(float(v))):,}"
    except (ValueError, TypeError):
        return "0"


def _period_bounds(period, year=None):
    """Return (start_iso, end_iso, label) for the given period."""
    today = datetime.now().date()
    if period == "weekly":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        label = f"Icyumweru: {start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"
    elif period == "monthly":
        start = today.replace(day=1)
        if today.month == 12:
            end = today.replace(day=31)
        else:
            end = (today.replace(month=today.month + 1, day=1) - timedelta(days=1))
        label = f"Ukwezi: {today.strftime('%B %Y')}"
    elif period == "yearly":
        year = year or today.year
        start = today.replace(year=year, month=1, day=1)
        end = today.replace(year=year, month=12, day=31)
        label = f"Umwaka: {year}"
    else:
        start = today - timedelta(days=30)
        end = today
        label = f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"
    return start.isoformat(), end.isoformat(), label


def _build_table_data(ranked, label):
    """Build the report table from rankings. Returns (data, styles, totals)."""
    header = [
        "RANK", "ITORERO", "PARUWASI", "AMATURO YOSE",
        "ABIHANNYE", "ABANA", "ABAGARUTSE",
        "UMUYOBOZI", "TELEPHONE",
    ]
    rows = [header]
    grand_total = 0
    total_abihannye = 0
    total_abana = 0
    total_abagarutse = 0
    for r in ranked:
        rows.append([
            str(r.get("rank", "")),
            r.get("name", ""),
            r.get("parish", ""),
            _fmt_money(r.get("total", 0)) + " RWF",
            str(r.get("abihannye", 0)),
            str(r.get("abana", 0)),
            str(r.get("abagarutse", 0)),
            r.get("leader_name", ""),
            r.get("leader_phone", ""),
        ])
        grand_total += float(r.get("total", 0) or 0)
        total_abihannye += int(r.get("abihannye", 0) or 0)
        total_abana += int(r.get("abana", 0) or 0)
        total_abagarutse += int(r.get("abagarutse", 0) or 0)
    # totals row
    rows.append([
        "", "IGITERANYO CYOSE", "", _fmt_money(grand_total) + " RWF",
        str(total_abihannye), str(total_abana), str(total_abagarutse),
        "", "",
    ])
    return rows, grand_total


def _table_style(num_rows):
    s = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), BOLD_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 1), (-1, -2), BASE_FONT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (2, -1), "LEFT"),
        ("ALIGN", (7, 1), (8, -1), "LEFT"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#475569")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f1f5f9")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fbbf24")),
        ("FONTNAME", (0, -1), (-1, -1), BOLD_FONT),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    return s


def _styles():
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title", parent=base["Normal"],
        fontName=BOLD_FONT, fontSize=14, alignment=TA_CENTER,
        textColor=colors.HexColor("#1e3a8a"),
    )
    subtitle = ParagraphStyle(
        "Subtitle", parent=base["Normal"],
        fontName=BASE_FONT, fontSize=10, alignment=TA_CENTER,
        textColor=colors.HexColor("#475569"),
    )
    period = ParagraphStyle(
        "Period", parent=base["Normal"],
        fontName=BOLD_FONT, fontSize=11, alignment=TA_CENTER,
        textColor=colors.HexColor("#1e40af"),
    )
    return title, subtitle, period


def create_offering_report(period="weekly", parish=None, output_folder=None, signer=None):
    """Generate a PDF offering report. Returns the path to the PDF."""
    output_folder = output_folder or db.REPORTS_DIR
    os.makedirs(output_folder, exist_ok=True)
    start_iso, end_iso, label = _period_bounds(period)
    ranked = db.rankings(parish=parish, start_date=start_iso, end_date=end_iso)

    profile = db.load_parish_profile()
    title_str = (profile.get("parish_name") or "ADEPR PARUWASI YA RUHANGO").upper()
    sub_str = "INCAMAKE Y'AMATURO Y'" + period.upper()

    rows, grand_total = _build_table_data(ranked, label)
    title_style, sub_style, period_style = _styles()

    today_str = datetime.now().strftime("%Y-%m-%d")
    file_name = f"{period.capitalize()}_Report_{today_str}.pdf"
    output_pdf = os.path.join(output_folder, file_name)

    doc = SimpleDocTemplate(
        output_pdf, pagesize=landscape(A4),
        rightMargin=12, leftMargin=12, topMargin=12, bottomMargin=12,
    )
    elements = []
    elements.append(Paragraph(title_str, title_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(sub_str, sub_style))
    elements.append(Spacer(1, 2))
    elements.append(Paragraph(label, period_style))
    elements.append(Spacer(1, 8))
    elements.append(get_company_header(profile))
    elements.append(Spacer(1, 8))

    col_widths = [0.5*inch, 1.6*inch, 1.2*inch, 1.4*inch,
                  0.8*inch, 0.7*inch, 0.9*inch, 1.6*inch, 1.3*inch]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(_table_style(len(rows))))
    elements.append(table)
    elements.append(Spacer(1, 12))

    # Footer with signatures
    elements.append(get_report_footer(profile, signer))

    doc.build(elements)
    return output_pdf


def export_excel(period="weekly", parish=None, output_folder=None):
    """Export the weekly report to .xlsx, mirroring the ADEPR Ruhango Parish
    sheet structure of "WEEKLY REPORT - 2.xlsx".

    Layout (one sheet "Ruhango Parish"):
      Row 1   (blank)
      Row 2   "IMBONERAHAMWE YA RAPORO Y'ICYUMWERU CYO KUWA <date>"
      Row 4   "ITORERO ADEPR"
      Row 5   "URUREMBO RW'AMAJYEPOFO"
      Row 6   "PARUWASI YA RUHANGO"
      Row 8   main header (merged vertically with row 9 where applicable)
      Row 9   Icyacumi sub-headers (Abihannye, Ibiturisho, Momo, Banki,
              Agasanduka, Igiteranyo)
      Row 10+ one row per church (No, ITORERO, then the 20 financial cols)
      Last    TOTAL row (sums)
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    output_folder = output_folder or db.REPORTS_DIR
    os.makedirs(output_folder, exist_ok=True)
    start_iso, end_iso, label = _period_bounds(period)
    ranked = db.rankings(parish=parish, start_date=start_iso, end_date=end_iso)
    profile = db.load_parish_profile()

    wb = Workbook()
    ws = wb.active
    ws.title = "Ruhango Parish"

    # ---- styles
    thin = Side(border_style="thin", color="475569")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor="1E40AF")
    sub_fill = PatternFill("solid", fgColor="3B82F6")
    total_fill = PatternFill("solid", fgColor="FBBF24")
    icyacumi_fill = PatternFill("solid", fgColor="DBEAFE")
    bold_white = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    bold = Font(name="Calibri", size=10, bold=True)
    normal = Font(name="Calibri", size=10)
    title_font = Font(name="Calibri", size=13, bold=True, color="1E3A8A")
    sub_title = Font(name="Calibri", size=11, bold=True, color="475569")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center")
    right = Alignment(horizontal="right", vertical="center")

    # ---- title rows (mirror reference rows 2, 4, 5, 6)
    today_str_date = datetime.now().strftime("%d/%m/%Y")
    ws["A2"] = "IMBONERAHAMWE YA RAPORO Y'ICYUMWERU CYO KUWA " + today_str_date
    ws["A2"].font = title_font
    ws["A2"].alignment = left
    ws["D4"] = "ITORERO ADEPR"
    ws["D4"].font = sub_title
    ws["D5"] = "URUREMBO RW'AMAJYEPOFO"
    ws["D5"].font = sub_title
    ws["D6"] = "PARUWASI YA RUHANGO"
    ws["D6"].font = Font(name="Calibri", size=11, bold=True, color="1E3A8A")

    # ---- 2-row merged header at rows 8-9, columns A..U (21 cols)
    HEADER_ROW1 = 8
    HEADER_ROW2 = 9
    DATA_START = 10

    # Column map (1-indexed): A=1 ... U=21
    # A: No | B: ITORERO | C: Abihannye | D-G: Icyacumi sub | H: Icyacumi Igiteranyo
    # I: Amaturo | J: Amashimwe | K: Buracyeye | L: Imisaruro | M: Igiteranyo
    # N: 7% | O: 2% Paruwasi | P: 2% Ururembo | Q: 89% HQ
    # R: Abana | S: Igiteranyo 89% + 50% Abana | T: Budget | U: %
    headers_top = {
        1: "No", 2: "ITORERO",
        4: "Icyacumi",     # D:G merged as Icyacumi group, H is its Igiteranyo
        9: "Amaturo", 10: "Amashimwe", 11: "Buracyeye / Nibature",
        12: "Imisaruro", 13: "Igiteranyo",
        14: "7% asigara ku itorero", 15: "2% Paruwasi",
        16: "2% Ururembo", 17: "89% azamuka kuri HQ",
        18: "Abana", 19: "Igiteranyo 89%+ 50% Abana",
        20: "Budget - icyumweru", 21: "%",
    }
    headers_sub = {  # row 9 sub-headers under Icyacumi (cols C-H)
        3: "Abihannye", 4: "Ibiturisho", 5: "Momo",
        6: "Banki", 7: "Agasanduka", 8: "Igiteranyo",
    }
    # write row 8 headers (merge vertical with row 9 for non-Icyacumi cols)
    for col, text in headers_top.items():
        cell = ws.cell(HEADER_ROW1, col, text)
        cell.font = bold_white
        cell.fill = header_fill
        cell.alignment = center
        cell.border = border
    # merge D8:G8 as "Icyacumi" group header (cols 4-7)
    ws.merge_cells(start_row=HEADER_ROW1, start_column=4,
                   end_row=HEADER_ROW1, end_column=7)
    # merge the single-cell headers vertically (row 8:9) for cols that have
    # NO sub-header in row 9. Cols 4-7 (Icyacumi sub) and 8 (Icyacumi total)
    # all have row-9 content, so they are NOT vertically merged.
    single_cols = [1, 2, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    for col in single_cols:
        ws.merge_cells(start_row=HEADER_ROW1, start_column=col,
                       end_row=HEADER_ROW2, end_column=col)
    # write row 9 sub-headers (cols C-H = 3-8)
    for col, text in headers_sub.items():
        cell = ws.cell(HEADER_ROW2, col, text)
        cell.font = bold_white
        cell.fill = sub_fill
        cell.alignment = center
        cell.border = border
    # also style the merged cell bottoms
    for col in range(1, 22):
        for r in (HEADER_ROW1, HEADER_ROW2):
            ws.cell(r, col).border = border

    # ---- data rows
    money_fmt = "#,##0"
    row_idx = DATA_START
    totals = {k: 0.0 for k in [
        "icyacumi_ibiturisho", "icyacumi_momo", "icyacumi_bank",
        "icyacumi_agasanduka", "icyacumi", "amaturo", "amashimwe",
        "buracyeye", "imisaruro", "igiteranyo", "church_7", "parish_2",
        "region_2", "hq_89", "abana_amount", "children_share",
        "hq_plus_children", "budget_icyumweru"]}
    total_abihannye = 0

    for i, r in enumerate(ranked, start=1):
        ws.cell(row_idx, 1, i).alignment = center
        ws.cell(row_idx, 2, r.get("name", "")).alignment = left
        ws.cell(row_idx, 3, int(r.get("abihannye", 0) or 0)).alignment = center
        # Icyacumi sub + total
        ws.cell(row_idx, 4, int(round(r.get("icyacumi_ibiturisho", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 5, int(round(r.get("icyacumi_momo", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 6, int(round(r.get("icyacumi_bank", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 7, int(round(r.get("icyacumi_agasanduka", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 8, int(round(r.get("icyacumi", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 9, int(round(r.get("amaturo", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 10, int(round(r.get("amashimwe", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 11, int(round(r.get("buracyeye", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 12, int(round(r.get("imisaruro", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 13, int(round(r.get("igiteranyo", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 14, int(round(r.get("church_7", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 15, int(round(r.get("parish_2", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 16, int(round(r.get("region_2", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 17, int(round(r.get("hq_89", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 18, int(round(r.get("abana_amount", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 19, int(round(r.get("hq_plus_children", 0) or 0))).number_format = money_fmt
        ws.cell(row_idx, 20, int(round(r.get("budget_icyumweru", 0) or 0))).number_format = money_fmt
        pct_cell = ws.cell(row_idx, 21, float(r.get("percent", 0) or 0))
        pct_cell.number_format = "0.00"
        # alignments + borders
        for col in range(4, 21):
            ws.cell(row_idx, col).alignment = right
        ws.cell(row_idx, 21).alignment = center
        for col in range(1, 22):
            cell = ws.cell(row_idx, col)
            cell.border = border
            if cell.font is None or not cell.font.bold:
                cell.font = normal
        # tint the Icyacumi group
        for col in range(4, 9):
            ws.cell(row_idx, col).fill = icyacumi_fill
        # accumulate totals
        for k in totals:
            totals[k] += float(r.get(k, 0) or 0)
        total_abihannye += int(r.get("abihannye", 0) or 0)
        row_idx += 1

    # ---- TOTAL row
    ws.cell(row_idx, 1, "").fill = total_fill
    ws.cell(row_idx, 2, "TOTAL").fill = total_fill
    ws.cell(row_idx, 3, total_abihannye).alignment = center
    ws.cell(row_idx, 4, int(round(totals["icyacumi_ibiturisho"]))).number_format = money_fmt
    ws.cell(row_idx, 5, int(round(totals["icyacumi_momo"]))).number_format = money_fmt
    ws.cell(row_idx, 6, int(round(totals["icyacumi_bank"]))).number_format = money_fmt
    ws.cell(row_idx, 7, int(round(totals["icyacumi_agasanduka"]))).number_format = money_fmt
    ws.cell(row_idx, 8, int(round(totals["icyacumi"]))).number_format = money_fmt
    ws.cell(row_idx, 9, int(round(totals["amaturo"]))).number_format = money_fmt
    ws.cell(row_idx, 10, int(round(totals["amashimwe"]))).number_format = money_fmt
    ws.cell(row_idx, 11, int(round(totals["buracyeye"]))).number_format = money_fmt
    ws.cell(row_idx, 12, int(round(totals["imisaruro"]))).number_format = money_fmt
    ws.cell(row_idx, 13, int(round(totals["igiteranyo"]))).number_format = money_fmt
    ws.cell(row_idx, 14, int(round(totals["church_7"]))).number_format = money_fmt
    ws.cell(row_idx, 15, int(round(totals["parish_2"]))).number_format = money_fmt
    ws.cell(row_idx, 16, int(round(totals["region_2"]))).number_format = money_fmt
    ws.cell(row_idx, 17, int(round(totals["hq_89"]))).number_format = money_fmt
    ws.cell(row_idx, 18, int(round(totals["abana_amount"]))).number_format = money_fmt
    ws.cell(row_idx, 19, int(round(totals["hq_plus_children"]))).number_format = money_fmt
    ws.cell(row_idx, 20, int(round(totals["budget_icyumweru"]))).number_format = money_fmt
    total_pct = (totals["igiteranyo"] / totals["budget_icyumweru"] * 100
                 if totals["budget_icyumweru"] > 0 else 0.0)
    pct_cell = ws.cell(row_idx, 21, round(total_pct, 2))
    pct_cell.number_format = "0.00"
    for col in range(1, 22):
        cell = ws.cell(row_idx, col)
        cell.border = border
        cell.font = bold
        cell.fill = total_fill
        if col >= 4 and col <= 20:
            cell.alignment = right
        elif col == 21:
            cell.alignment = center
        elif col == 3:
            cell.alignment = center

    # ---- column widths (21 cols)
    widths = [5, 18, 9, 11, 9, 9, 11, 12, 12, 11, 13, 11, 13, 13, 12, 12, 14, 10, 16, 14, 9]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[HEADER_ROW1].height = 28
    ws.row_dimensions[HEADER_ROW2].height = 24

    ws.freeze_panes = "C10"

    today_str = datetime.now().strftime("%Y-%m-%d")
    out = os.path.join(output_folder, f"{period.capitalize()}_Export_{today_str}.xlsx")
    wb.properties.creator = "ADEPR MIS — Paruwasi ya Ruhango"
    wb.properties.title = "Imbonerahamwe ya raporo y'icyumweru"
    wb.save(out)
    return out
