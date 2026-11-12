"""
helpers.py — ReportLab helpers for PDF reports.
Provides: company header table, report footer (with signature + verification QR),
base table style. Mirrors the reference helpers.py but adapted for the church.
"""

import os
import json
import hashlib
from datetime import datetime

from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, Image, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import db

_FONT_OK = False
try:
    pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
    _FONT_OK = True
except Exception:
    pass
BASE_FONT = "DejaVu" if _FONT_OK else "Helvetica"
BOLD_FONT = "DejaVu-Bold" if _FONT_OK else "Helvetica-Bold"


def _styles():
    base = getSampleStyleSheet()
    return {
        "normal": ParagraphStyle("Normal", parent=base["Normal"],
                                 fontName=BASE_FONT, fontSize=9),
        "bold": ParagraphStyle("Bold", parent=base["Normal"],
                               fontName=BOLD_FONT, fontSize=9),
        "small": ParagraphStyle("Small", parent=base["Normal"],
                                fontName=BASE_FONT, fontSize=8,
                                textColor=colors.HexColor("#475569")),
        "center": ParagraphStyle("Center", parent=base["Normal"],
                                 fontName=BASE_FONT, fontSize=10,
                                 alignment=TA_CENTER),
    }


def get_company_header(profile):
    """2-column header: parish info on the left, contact on the right."""
    s = _styles()
    left = [
        Paragraph(profile.get("parish_name", "ADEPR PARUWASI YA RUHANGO"),
                  ParagraphStyle("H", parent=s["bold"], fontSize=12,
                                 textColor=colors.HexColor("#1e3a8a"))),
        Paragraph(profile.get("region", ""), s["small"]),
        Paragraph(profile.get("address", ""), s["small"]),
        Paragraph("TIN: " + (profile.get("tin") or "—"), s["small"]),
    ]
    right = [
        Paragraph("<b>Umushumba wa Paruwasi:</b> " + profile.get("pastor_name", ""),
                  s["normal"]),
        Paragraph("Telefone: " + profile.get("pastor_phone", ""), s["normal"]),
        Paragraph("Email: " + profile.get("pastor_email", ""), s["normal"]),
        Paragraph("Itariki: " + datetime.now().strftime("%d/%m/%Y"), s["small"]),
    ]
    data = [[left, right]]
    t = Table(data, colWidths=[4.6 * inch, 4.6 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#1e40af")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _signature_image(user_id, width=1.6 * inch, height=0.5 * inch):
    """Return a ReportLab Image for a user's saved signature, or None."""
    try:
        sig = db.get_signature(user_id)
        b64 = sig.get("png_base64", "")
        if not b64:
            return None
        if "base64," in b64:
            b64 = b64.split("base64,", 1)[1]
        import base64
        path = os.path.join(db.DATA_DIR, f"_sig_{user_id}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        return Image(path, width=width, height=height)
    except Exception:
        return None


def get_report_footer(profile, signer=None):
    """Footer with: prepared-by signature + approver signature + verification hash."""
    s = _styles()
    sig_left_cell = ""
    sig_right_cell = ""
    name_left = "Uwatanguye raporo"
    name_right = "Umushumba wa Paruwasi"

    if signer and signer.get("id"):
        img = _signature_image(signer["id"])
        if img:
            sig_left_cell = img
            name_left = signer.get("name", "Uwatanguye raporo")

    # Parish pastor signature (right)
    parish_pastors = [u for u in db.list_users(active_only=True)
                      if u.get("role") == "PARISH_PASTOR"]
    if parish_pastors:
        pp = parish_pastors[0]
        img2 = _signature_image(pp["id"])
        if img2:
            sig_right_cell = img2
            name_right = pp.get("name", "Umushumba wa Paruwasi")
        else:
            name_right = pp.get("name", "Umushumba wa Paruwasi")

    # Verification payload (hash)
    payload = {
        "parish": profile.get("parish_name"),
        "tin": profile.get("tin"),
        "date": datetime.now().isoformat(timespec="seconds"),
        "signed_by": name_left,
        "approved_by": name_right,
    }
    h = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    verify = Paragraph(
        "<b>Verify:</b> " + h,
        ParagraphStyle("V", parent=s["small"], fontSize=7,
                       textColor=colors.HexColor("#64748b"))
    )

    spacer = Paragraph("&nbsp;", s["normal"])
    sig_table = Table(
        [[sig_left_cell or spacer, sig_right_cell or spacer],
         [Paragraph("<b>" + name_left + "</b>", s["center"]),
          Paragraph("<b>" + name_right + "</b>", s["center"])],
         [Paragraph("Uwatanguye raporo", s["small"]),
          Paragraph("Umushumba wa Paruwasi", s["small"])]],
        colWidths=[4.6 * inch, 4.6 * inch],
    )
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#475569")),
        ("TOPPADDING", (0, 0), (-1, 0), 24),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
    ]))
    return KeepTogether([sig_table, Spacer(1, 6), verify])


def get_base_table_style():
    return [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), BOLD_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#475569")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
