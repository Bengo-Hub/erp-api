"""
Branding-aware employment contract PDF generation.

Mirrors the existing reportlab-based document stack in this repo
(core/modules/report_export.py -> export_report_to_pdf): same library
(reportlab / platypus), same header+footer convention, and tenant branding is
pulled from auth-api via integrations.branding.get_tenant_branding (the single
source of truth, never stored locally — see feedback_document_generation_architecture).

Kept as a focused, self-contained module (feedback_file_length_modular).

Public API:
    build_contract_pdf_bytes(contract, branding=None) -> bytes
    render_contract_pdf_response(contract, request=None) -> HttpResponse
"""
from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

_DEFAULT_PRIMARY = "#366092"  # matches report_export.py header colour


def _resolve_branding(request):
    """Fetch tenant branding for the request, tolerating missing context."""
    try:
        from integrations.branding import get_tenant_branding
        slug = ""
        claims = getattr(request, "auth_claims", None) if request is not None else None
        if claims is not None:
            slug = getattr(claims, "tenant_slug", "") or ""
        return get_tenant_branding(slug=slug, request=request) or {}
    except Exception:  # pragma: no cover - branding must never break the document
        logger.warning("contract_pdf: branding lookup failed", exc_info=True)
        return {}


def _employee_name(contract) -> str:
    try:
        user = contract.employee.user
        full = (f"{user.first_name} {user.last_name}").strip()
        return full or getattr(user, "email", "") or "Employee"
    except Exception:
        return "Employee"


def _employee_email(contract) -> str:
    try:
        return getattr(contract.employee.user, "email", "") or ""
    except Exception:
        return ""


def _fmt_date(value) -> str:
    if not value:
        return "-"
    try:
        return value.strftime("%d %b %Y")
    except Exception:
        return str(value)


def _fmt_money(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def _primary_color(branding: dict):
    raw = (branding or {}).get("primary_color") or _DEFAULT_PRIMARY
    try:
        return colors.HexColor(raw if str(raw).startswith("#") else f"#{raw}")
    except Exception:
        return colors.HexColor(_DEFAULT_PRIMARY)


def build_contract_pdf_bytes(contract, branding=None) -> bytes:
    """Render the employment ``contract`` to PDF bytes using tenant ``branding``."""
    branding = branding or {}
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=0.6 * inch, bottomMargin=0.5 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    primary = _primary_color(branding)

    title_style = ParagraphStyle(
        "ContractCompany", parent=styles["Heading1"], fontSize=18,
        textColor=primary, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ContractSubtitle", parent=styles["Normal"], fontSize=9, textColor=colors.grey,
    )
    doc_title_style = ParagraphStyle(
        "ContractDocTitle", parent=styles["Heading2"], fontSize=14,
        textColor=colors.HexColor("#1a1a1a"), spaceBefore=10, spaceAfter=8,
    )
    label_style = ParagraphStyle(
        "ContractLabel", parent=styles["Normal"], fontSize=9,
        textColor=colors.grey,
    )
    value_style = ParagraphStyle(
        "ContractValue", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#1a1a1a"),
    )
    body_style = ParagraphStyle(
        "ContractBody", parent=styles["Normal"], fontSize=9.5, leading=14,
    )

    elements = []

    # --- Branding header (logo + tenant name + statutory/address lines) ---
    company_name = branding.get("name") or "BengoERP"
    elements.append(Paragraph(company_name, title_style))
    header_bits = []
    if branding.get("address"):
        header_bits.append(str(branding["address"]))
    if branding.get("kra_pin"):
        header_bits.append(f"KRA PIN: {branding['kra_pin']}")
    if header_bits:
        elements.append(Paragraph(" | ".join(header_bits), subtitle_style))
    elements.append(Spacer(1, 0.12 * inch))

    elements.append(Paragraph("EMPLOYMENT CONTRACT", doc_title_style))

    # --- Contract detail grid ---
    type_display = contract.get_contract_type_display() if hasattr(contract, "get_contract_type_display") else contract.contract_type
    pay_display = contract.get_pay_type_display() if hasattr(contract, "get_pay_type_display") else contract.pay_type
    status_display = contract.get_status_display() if hasattr(contract, "get_status_display") else contract.status

    rows = [
        ("Employee", _employee_name(contract)),
        ("Email", _employee_email(contract)),
        ("Contract Type", type_display or "-"),
        ("Status", status_display or "-"),
        ("Start Date", _fmt_date(contract.contract_start_date)),
        ("End Date", _fmt_date(contract.contract_end_date)),
        ("Probation End", _fmt_date(getattr(contract, "probation_end_date", None))),
        ("Salary", _fmt_money(contract.salary)),
        ("Pay Type", pay_display or "-"),
    ]

    table_data = [
        [Paragraph(label, label_style), Paragraph(str(value), value_style)]
        for label, value in rows
    ]
    detail_table = Table(table_data, colWidths=[1.8 * inch, 4.6 * inch])
    detail_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e0e0e0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7f9fc")),
    ]))
    elements.append(detail_table)
    elements.append(Spacer(1, 0.2 * inch))

    # --- Terms / notes ---
    terms = (getattr(contract, "notes", None) or "").strip()
    if terms:
        elements.append(Paragraph("Terms & Conditions", doc_title_style))
        for line in terms.splitlines():
            line = line.strip()
            if line:
                elements.append(Paragraph(line, body_style))
        elements.append(Spacer(1, 0.2 * inch))

    # --- Signature block ---
    elements.append(Spacer(1, 0.3 * inch))
    sig_data = [
        [Paragraph("_____________________________", value_style),
         Paragraph("_____________________________", value_style)],
        [Paragraph("Employee Signature & Date", label_style),
         Paragraph(f"For and on behalf of {company_name}", label_style)],
    ]
    sig_table = Table(sig_data, colWidths=[3.2 * inch, 3.2 * inch])
    sig_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(sig_table)

    # --- Footer ---
    elements.append(Spacer(1, 0.25 * inch))
    footer = f"Generated by {company_name} on {datetime.now().strftime('%Y-%m-%d %H:%M')} | Confidential"
    elements.append(Paragraph(
        footer,
        ParagraphStyle("ContractFooter", parent=styles["Normal"], fontSize=8,
                       textColor=colors.grey, alignment=1),
    ))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def render_contract_pdf_response(contract, request=None) -> HttpResponse:
    """Build an ``application/pdf`` HttpResponse for the given contract."""
    branding = _resolve_branding(request)
    pdf_bytes = build_contract_pdf_bytes(contract, branding=branding)
    filename = f"contract_{contract.pk}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
