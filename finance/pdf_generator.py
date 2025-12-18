"""Shared PDF generation helpers for invoices and quotations.

This module exposes two simple wrappers:
- `generate_invoice_pdf(invoice, company_info=None)`
- `generate_quotation_pdf(quotation, company_info=None)`

Both delegate to `_generate_order_pdf` which contains the shared logic.
"""

from io import BytesIO
from datetime import datetime
from decimal import Decimal
import logging

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from typing import cast

from .utils import (
    _get_logo_image,
    _sanitize_text_for_pdf,
    _safe_str,
    _build_company_details_section,
    _build_client_details_section,
    _build_document_details_section,
    get_customer_name,
    get_customer_email,
    get_customer_phone,
    BoxedSection,
    get_brand_color,
)

logger = logging.getLogger(__name__)


def generate_invoice_pdf(invoice, company_info=None, document_type='invoice'):
    """Generate invoice PDF bytes. Accept optional `document_type` (packing_slip, delivery_note)."""
    return _generate_order_pdf(invoice, company_info=company_info, document_type=document_type)


def generate_quotation_pdf(quotation, company_info=None, document_type='quotation'):
    """Generate quotation PDF bytes."""
    return _generate_order_pdf(quotation, company_info=company_info, document_type=document_type)


def _format_currency(value):
    try:
        v = Decimal(value or 0)
    except Exception:
        v = Decimal(0)
    return f"KES {v.quantize(Decimal('0.01')):,.2f}"


def _format_date(d):
    """Return a human-friendly date string (dd/mm/YYYY) or None."""
    try:
        if not d:
            return None
        return d.strftime('%d/%m/%Y')
    except Exception:
        try:
            return str(d)
        except Exception:
            return None


def _generate_order_pdf(order, company_info=None, document_type='invoice'):
    """Shared generator used for invoices and quotations.

    It builds a minimal, robust PDF that includes company header, document
    meta (invoice/quotation number, dates), customer details, line items and
    totals. Document-specific fields such as `rfq_number` and
    `tender_quotation_ref` are included for quotations.
    """
    buffer = BytesIO()
    try:
        # Create page footer function
        def _create_page_footer(canvas, doc, order=order, company_info=company_info):
            """Draw footer on each page."""
            canvas.saveState()
            # Get company website
            website = company_info.get('website', '') if company_info else ''
            if not website:
                website = 'www.masterspace.co.ke'
            
            footer_text = 'Thank you for your business!'
            gen_text = f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            
            # Footer line on top
            footer_y = 0.5 * inch
            canvas.setLineWidth(0.5)
            canvas.line(36, footer_y + 0.15 * inch, A4[0] - 36, footer_y + 0.15 * inch)
            
            # Left: Thank you text
            canvas.setFont('Helvetica', 9)
            canvas.drawString(36, footer_y, footer_text)
            
            # Right: Generated date
            canvas.drawRightString(A4[0] - 36, footer_y, gen_text)
            
            # Middle: Website
            website_width = canvas.stringWidth(website, 'Helvetica', 9)
            mid_x = (A4[0] - 36 + 36) / 2 - (website_width / 2)
            canvas.drawString(mid_x, footer_y, website)
            
            canvas.restoreState()
        
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        elements = []

        # Build helper pieces
        logo = _get_logo_image(company_info)
        company_section = _build_company_details_section(company_info)
        #print(f"Company section for PDF generation: {company_section}")
        client_info = {
            'name': get_customer_name(order),
            'email': get_customer_email(order),
            'phone': get_customer_phone(order),

        }
        client_section = _build_client_details_section(client_info, document_type)

        # Build a document info dict expected by utils
        document_info = {
            'number': getattr(order, 'invoice_number', None) or getattr(order, 'quotation_number', None) or getattr(order, 'order_number', None),
            'date': _format_date(getattr(order, 'invoice_date', None) or getattr(order, 'quotation_date', None) or getattr(order, 'created_at', None)),
            'due_date': _format_date(getattr(order, 'due_date', None)),
            'valid_until': _format_date(getattr(order, 'valid_until', None)),
            'rfq_number': getattr(order, 'rfq_number', None),
            'tender_quotation_ref': getattr(order, 'tender_quotation_ref', None),
            'expected_delivery': _format_date(getattr(order, 'expected_delivery', None)),
        }

        # Determine brand color and text color for styling
        brand_color = get_brand_color(company_info or {})
        text_color = company_info.get('text_color', '') if company_info else ''
        if text_color:
            try:
                text_color = colors.HexColor(text_color) if isinstance(text_color, str) else text_color
            except Exception:
                text_color = colors.HexColor('#FFFEF0')  # Light creamy white fallback
        else:
            text_color = colors.HexColor('#FFFEF0')  # Light creamy white fallback
        elements.extend(_render_header(company_section, client_section, document_info, logo, document_type, styles, brand_color))
        elements.append(Spacer(1, 0.15 * inch))

        # Delivery note intro for LPO/delivery_note
        if document_type in ['delivery_note', 'packing_slip']:
            elements.append(Paragraph('<b>Received the following goods in good condition:</b>', styles['Normal']))
            elements.append(Spacer(1, 0.08 * inch))

        # Items table (separated helper)
        items_table, subtotal = _render_items_table(order, styles, brand_color, text_color)
        elements.append(items_table)
        elements.append(Spacer(1, 0.2 * inch))

        # Totals (separated helper)
        totals_table = _render_totals_table(order, subtotal, styles, brand_color)
        elements.append(totals_table)

        # Footer / Prepared & Approved (footer helper will include notes & terms)
        elements.append(Spacer(1, 0.25 * inch))
        elements.extend(_render_footer(order, styles, document_type, brand_color))

        # Build document with page footer (removes "Thank you" and "Generated" from content)
        doc.build(elements, onFirstPage=_create_page_footer, onLaterPages=_create_page_footer)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        logger.info(f"Generated {document_type} PDF for {getattr(order, 'invoice_number', getattr(order, 'quotation_number', getattr(order, 'order_number', 'unknown')))}")
        return pdf_bytes

    except Exception:
        logger.exception("Error generating PDF")
        raise


def _render_items_table(order, styles, brand_color=None, text_color=None):
    """Build and return the items Table plus subtotal value."""
    items = getattr(order, 'items', None)
    
    # Ensure text_color is a valid reportlab color object
    header_text_color = text_color if text_color else colors.HexColor('#FFFEF0')
    
    # Create header style with the branding text color
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        textColor=header_text_color,
        fontName='Helvetica-Bold',
        fontSize=10
    )
    
    rows = [[
        Paragraph('#', header_style),
        Paragraph('Description', header_style),
        Paragraph('Qty', header_style),
        Paragraph('Unit', header_style),
        Paragraph('Tax', header_style),
        Paragraph('Amount', header_style)
    ]]
    
    subtotal = Decimal(0)
    if items is not None:
        for idx, it in enumerate(items.all(), 1):
            desc = _sanitize_text_for_pdf(getattr(it, 'name', '') or '')
            if getattr(it, 'description', None):
                desc += '<br/>' + _sanitize_text_for_pdf(it.description).replace('\n', '<br/>')
            qty = getattr(it, 'quantity', 1)
            unit = getattr(it, 'unit_price', 0)
            tax = getattr(it, 'tax_amount', 0)
            tax_type = getattr(it, 'tax_type', '') or ''
            total = getattr(it, 'total_price', None) or (Decimal(qty) * Decimal(unit))
            subtotal += Decimal(total)
            rows.append([
                Paragraph(str(idx), styles['Normal']),
                Paragraph(desc, styles['Normal']),
                Paragraph(str(qty), styles['Normal']),
                Paragraph(_format_currency(unit), styles['Normal']),
                Paragraph(f"{tax_type} { _format_currency(tax) if tax else ''}", styles['Normal']),
                Paragraph(_format_currency(total), styles['Normal']),
            ])

    items_table = Table(rows, colWidths=[0.4 * inch, 3.6 * inch, 0.6 * inch, 1.2 * inch, 1.0 * inch, 1.4 * inch])
    header_bg = brand_color or colors.HexColor('#2563eb')
    
    items_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
    ]))
    return items_table, subtotal


def _render_totals_table(order, subtotal, styles, brand_color=None):
    """Build and return totals Table (subtotal, tax, discount, shipping, total)."""
    # If tax_mode == 'on_total' use order.tax_rate to compute tax, else sum per-line tax_amount
    tax_total = 0
    items = getattr(order, 'items', None)
    if getattr(order, 'tax_mode', None) == 'on_total' and getattr(order, 'tax_rate', None) is not None:
        try:
            tax_total = (Decimal(subtotal) * Decimal(getattr(order, 'tax_rate', 0))) / Decimal(100)
        except Exception:
            tax_total = getattr(order, 'tax_total', 0) or 0
    else:
        tax_total = getattr(order, 'tax_total', None) or getattr(order, 'total_tax', None) or sum([getattr(it, 'tax_amount', 0) or 0 for it in (items.all() if items is not None else [])])

    totals = []
    totals.append([Paragraph('Subtotal', styles['Normal']), Paragraph(_format_currency(subtotal), styles['Normal'])])
    if tax_total:
        if getattr(order, 'tax_mode', None) == 'on_total':
            label = f"Tax ({getattr(order, 'tax_rate', 0)}%)"
        else:
            label = 'Tax'
        totals.append([Paragraph(label, styles['Normal']), Paragraph(_format_currency(tax_total), styles['Normal'])])

    discount = getattr(order, 'discount_total', None) or getattr(order, 'discount_amount', None) or getattr(order, 'discount', 0) or 0
    if discount:
        totals.append([Paragraph('Discount', styles['Normal']), Paragraph(_format_currency(discount), styles['Normal'])])

    shipping = getattr(order, 'shipping_cost', 0) or 0
    if shipping:
        totals.append([Paragraph('Shipping', styles['Normal']), Paragraph(_format_currency(shipping), styles['Normal'])])

    grand = getattr(order, 'grand_total', None) or getattr(order, 'total', None) or (Decimal(subtotal) + Decimal(tax_total) + Decimal(shipping) - Decimal(discount))
    totals.append([Paragraph('<b>Total</b>', styles['Normal']), Paragraph(f"<b>{_format_currency(grand)}</b>", styles['Normal'])])

    totals_table = Table(totals, colWidths=[6.6 * inch, 1.4 * inch])
    line_color = brand_color or colors.black
    totals_table.setStyle(TableStyle([
        ('LINEABOVE', (0, -1), (-1, -1), 1, line_color),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    return totals_table


def _render_header(company_section, client_section, document_info, logo, document_type, styles, brand_color=None):
    """Return flowables that render the top header with title, logo, company and client details and document meta."""
    flowables = []

    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], alignment=TA_CENTER, fontName='Helvetica-Bold', fontSize=18, textColor=(brand_color or colors.HexColor('#1f2937')))
    title = Paragraph(document_type.upper(), title_style)

    # Centered title
    flowables.append(title)
    flowables.append(Spacer(1, 0.06 * inch))

    # Compute available content width (A4 minus left/right margins used in _generate_order_pdf)
    content_width_pts = A4[0] - 36 - 36
    # Reduce left boxes (company/client) by 2 inches as requested (was 5.0*inch)
    left_box_width_pts = 3.0 * inch
    right_box_width_pts = content_width_pts - left_box_width_pts
    min_right = 1.5 * inch
    if right_box_width_pts < min_right:
        right_box_width_pts = min_right
        left_box_width_pts = max(content_width_pts - right_box_width_pts, 1.0 * inch)

    # Below title: company details (left) and logo (right)
    if company_section:
        comp_box = BoxedSection(company_section, width=left_box_width_pts, padding=6, stroke=(brand_color or colors.HexColor('#e5e7eb')), fill=None, radius=4)
        right_logo = logo if logo else Paragraph('', styles['Normal'])
        comp_logo_tbl = Table([[comp_box, right_logo]], colWidths=[left_box_width_pts, right_box_width_pts])
        # Right-align the logo inside its column so the logo's right edge aligns
        # with the right edge of the document-details box below (both use the
        # same right-column width). Left-column boxes (company/client) already
        # share the same width so their left edges align as well.
        comp_logo_tbl.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))
        flowables.append(comp_logo_tbl)
        flowables.append(Spacer(1, 0.06 * inch))

    # Then: client details (left, boxed) and document details (right, boxed) with rectangles starting at same left x and widths based on content
    client_col = []
    if client_section:
        client_box = BoxedSection(client_section, width=left_box_width_pts, padding=4, stroke=(brand_color or colors.HexColor('#e5e7eb')), fill=None, radius=4)
        client_col.append(client_box)
    else:
        client_col.append(Paragraph('', styles['Normal']))

    doc_details = _build_document_details_section(document_info, document_type)
    # Build document table content (doc_table may be None if doc_details is empty)
    doc_table = None
    if doc_details:
        doc_table = Table([[p] for p in doc_details])
        doc_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))

    # Calculate logo width inside the right column; if logo absent, no offset
    logo_width_pts = 0
    try:
        if logo and getattr(logo, 'drawWidth', None):
            logo_width_pts = logo.drawWidth
        elif logo and getattr(logo, 'imageWidth', None):
            logo_width_pts = logo.imageWidth
    except Exception:
        logo_width_pts = 0

    # If we have a logo width, compute an inner left spacer so the doc_box starts
    # at the same x as the logo's left edge (logo is right-aligned in its column).
    if logo_width_pts and logo_width_pts < right_box_width_pts:
        doc_left_offset = right_box_width_pts - logo_width_pts
        # Make the document box wider by 2 inches if possible, but don't exceed right column
        desired_doc_width = min(logo_width_pts + (2.0 * inch), right_box_width_pts)
    else:
        # No logo: position at column start, use full right column width
        doc_left_offset = 0
        # Use the full right column width for document details
        desired_doc_width = right_box_width_pts

    # Ensure desired width is valid and doesn't exceed available space
    desired_doc_width = min(max(desired_doc_width, 1.0 * inch), right_box_width_pts)

    # Build nested right column only if we have document details to show
    if doc_details:
        # Calculate trailing space for proper alignment
        trailing = max(0, right_box_width_pts - doc_left_offset - desired_doc_width)
        # Recreate doc_box with the desired width
        doc_box = BoxedSection([doc_table] if doc_details else [], width=desired_doc_width, padding=4, stroke=(brand_color or colors.HexColor('#e5e7eb')), fill=None, radius=4)

        # Build right nested table with proper spacing
        right_cols = []
        right_widths = []
        
        if doc_left_offset > 0:
            right_cols.append(Spacer(doc_left_offset, 0))
            right_widths.append(doc_left_offset)
        
        right_cols.append(doc_box)
        right_widths.append(desired_doc_width)
        
        if trailing > 0:
            right_cols.append(Spacer(trailing, 0))
            right_widths.append(trailing)
        
        right_nested = Table([right_cols], colWidths=right_widths)
        right_nested.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    else:
        # No document details, just use an empty spacer
        right_nested = Spacer(right_box_width_pts, 0)
    row_tbl = Table([[client_col[0], right_nested]], colWidths=[left_box_width_pts, right_box_width_pts])
    row_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT')
    ]))
    flowables.append(row_tbl)

    return flowables


def _render_footer(order, styles, document_type='invoice', brand_color=None):
    """Return flowables for the document footer (notes, terms, prepared/approved/signatures).

    For delivery notes, include Received by fields.
    """
    flowables = []

    # Notes & Terms
    if getattr(order, 'customer_notes', None):
        flowables.append(Paragraph('<b>Notes</b>', styles['Normal']))
        flowables.append(Paragraph(_sanitize_text_for_pdf(order.customer_notes).replace('\n', '<br/>'), styles['Normal']))
        flowables.append(Spacer(1, 0.1 * inch))

    if getattr(order, 'terms_and_conditions', None):
        flowables.append(Paragraph('<b>Terms & Conditions</b>', styles['Normal']))
        flowables.append(Paragraph(_sanitize_text_for_pdf(order.terms_and_conditions).replace('\n', '<br/>'), styles['Normal']))
        flowables.append(Spacer(1, 0.1 * inch))

    # Prepared / Approved signatures block - resolve from document users/dates
    def _extract_user(u):
        """Return (display_name, email, initials) for a user-like object or string."""
        if not u:
            return ('', '', '')
        # If it's a string, treat it as email
        if isinstance(u, str):
            parts = u.split('@')
            initials = (parts[0][0] if parts[0] else '')
            return (u, u, initials.upper())
        # Try common user attributes
        first = getattr(u, 'first_name', '') or getattr(u, 'name', '') or ''
        last = getattr(u, 'last_name', '') or ''
        email = getattr(u, 'email', '') or getattr(u, 'username', '') or ''
        display = f"{first} {last}".strip() or email or ''
        initials = ((first[:1] or '') + (last[:1] or '')).upper()
        return (display, email, initials)

    prepared_user = getattr(order, 'created_by', None) or getattr(order, 'prepared_by', None)
    approved_user = getattr(order, 'approved_by', None)
    prepared_name, prepared_email, prepared_initials = _extract_user(prepared_user)
    approved_name, approved_email, approved_initials = _extract_user(approved_user)

    prepared_date = getattr(order, 'created_at', None) or None
    approved_date = getattr(order, 'approved_at', None) or getattr(order, 'approved_on', None) or None

    # Create signature lines - each on single horizontal line with balanced spacing
    doc_width = 7.0 * inch  # Approximate document width (A4 minus margins)
    
    prepared_str = f"Prepared by: {prepared_name}"
    prepared_date_str = f"Date: {prepared_date.strftime('%d/%m/%Y') if prepared_date else '________'}"
    prepared_sig_str = f"Sign: {prepared_initials if prepared_initials else '________'}"
    
    approved_str = f"Approved by: {approved_name}"
    approved_date_str = f"Date: {approved_date.strftime('%d/%m/%Y') if approved_date else '________'}"
    approved_sig_str = f"Sign: {approved_initials if approved_initials else '________'}"
    
    # Prepared line: balance across the width
    prepared_cols = [
        Paragraph(prepared_str, styles['Normal']),
        Paragraph(prepared_date_str, styles['Normal']),
        Paragraph(prepared_sig_str, styles['Normal'])
    ]
    prepared_line = Table([prepared_cols], colWidths=[2.5 * inch, 2.0 * inch, 2.5 * inch])
    prepared_line.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    
    # Approved line: balance across the width  
    approved_cols = [
        Paragraph(approved_str, styles['Normal']),
        Paragraph(approved_date_str, styles['Normal']),
        Paragraph(approved_sig_str, styles['Normal'])
    ]
    approved_line = Table([approved_cols], colWidths=[2.5 * inch, 2.0 * inch, 2.5 * inch])
    approved_line.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    
    sig_table = Table([[prepared_line], [approved_line]], colWidths=[doc_width])
    sig_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    flowables.append(sig_table)

    # Delivery note special footer for Received by
    if document_type in ['delivery_note', 'packing_slip']:
        flowables.append(Spacer(1, 0.15 * inch))
        flowables.append(Paragraph('<b>Received by</b>', styles['Normal']))
        recv_table = Table([[Paragraph('Name: ______________________', styles['Normal']), Paragraph('Date: __________', styles['Normal'])], [Paragraph('Signature: ______________________', styles['Normal']), '']], colWidths=[4 * inch, 3 * inch])
        recv_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        flowables.append(recv_table)

    # For quotations, show public URL and accepted/rejected info if present
    if document_type == 'quotation':
        public_url = getattr(order, 'public_url', None) or getattr(order, 'quote_public_url', None)
        accepted_by = getattr(order, 'accepted_by', None)
        accepted_at = getattr(order, 'accepted_at', None)
        rejected_by = getattr(order, 'rejected_by', None)
        rejected_at = getattr(order, 'rejected_at', None)
        if public_url:
            flowables.append(Spacer(1, 0.1 * inch))
            flowables.append(Paragraph(f"Public URL: {_safe_str(public_url)}", styles['Normal']))
        if accepted_by or accepted_at:
            ab = getattr(accepted_by, 'email', accepted_by if isinstance(accepted_by, str) else '')
            flowables.append(Paragraph(f"Accepted by: {ab} on {accepted_at.strftime('%d/%m/%Y') if accepted_at else ''}", styles['Normal']))
        if rejected_by or rejected_at:
            rb = getattr(rejected_by, 'email', rejected_by if isinstance(rejected_by, str) else '')
            flowables.append(Paragraph(f"Rejected by: {rb} on {rejected_at.strftime('%d/%m/%Y') if rejected_at else ''}", styles['Normal']))

    return flowables

