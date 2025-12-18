"""
Professional Invoice PDF Generation using ReportLab
Generates print-ready invoices with company branding
"""
from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from datetime import datetime
from decimal import Decimal
import logging
import os
from ..utils import (
    get_customer_name, get_customer_email, get_customer_phone,
    _sanitize_text_for_pdf, _get_logo_image, _build_company_details_section,
    _build_client_details_section, _build_document_details_section, BoxedSection
)


def _format_date_safe(d):
    try:
        if not d:
            return ''
        if hasattr(d, 'strftime'):
            return d.strftime('%d/%m/%Y')
        return str(d)
    except Exception:
        try:
            return str(d)
        except Exception:
            return ''
logger = logging.getLogger(__name__)
from django.conf import settings
import re
import html
try:
    from django.contrib.staticfiles import finders
except Exception:
    finders = None

# BoxedSection is provided by finance.utils; imported above for reuse.


def _resolve_company_from_document(doc):
    """Attempt to construct a company_info dict from a document (invoice/quotation)
    Falls back to provided branch.business if available."""
    # now implemented in finance.utils as _resolve_company_from_document
    from ..utils import _resolve_company_from_document as _impl
    return _impl(doc)


def _user_initials(user):
    try:
        if not user:
            return ''
        fn = getattr(user, 'first_name', '') or ''
        ln = getattr(user, 'last_name', '') or ''
        parts = [p for p in [fn, ln] if p]
        if parts:
            return ''.join([p[0].upper() for p in parts])
        return getattr(user, 'username', '')[:2].upper()
    except Exception:
        return ''


def _build_signature_table(prepared_by, approved_by, header_style, prepared_date=None, approved_date=None):
    """Return a signature Table flowable for prepared/approved details.

    prepared_date and approved_date can be provided as strings (formatted) or datetime objects.
    """
    prepared_name = f"{getattr(prepared_by, 'first_name', '') or ''} {getattr(prepared_by, 'last_name', '') or ''}".strip() if prepared_by else ''
    approved_name = f"{getattr(approved_by, 'first_name', '') or ''} {getattr(approved_by, 'last_name', '') or ''}".strip() if approved_by else ''

    if prepared_date and hasattr(prepared_date, 'strftime'):
        prepared_date_str = prepared_date.strftime('%d/%m/%Y')
    else:
        prepared_date_str = prepared_date or ''

    if approved_date and hasattr(approved_date, 'strftime'):
        approved_date_str = approved_date.strftime('%d/%m/%Y')
    else:
        approved_date_str = approved_date or ''

    sig_table = Table([
        [Paragraph('<b>Prepared by</b>', header_style), Paragraph('<b>Approved by</b>', header_style)],
        [Paragraph(prepared_name, header_style), Paragraph(approved_name, header_style)],
        [Paragraph(prepared_date_str, header_style), Paragraph(approved_date_str, header_style)],
        [Paragraph(f"Sign: { _user_initials(prepared_by) }", header_style), Paragraph(f"Sign: { _user_initials(approved_by) }", header_style)]
    ], colWidths=[3.5*inch, 3.5*inch])
    return sig_table


def _build_totals_table(document, document_type, label_style, label_bold_style):
    """Construct and return a totals Table for invoice/quotation with tax label handling."""
    # Determine a friendly tax label depending on tax_mode and tax_rate
    tax_label = getattr(document, 'tax_type', None) or 'Tax'
    try:
        if getattr(document, 'tax_mode', None) == 'on_total':
            rate = getattr(document, 'tax_rate', None)
            if rate is not None and str(rate) != '':
                # show percentage and indicate tax is on subtotal/total
                tax_label = f"Tax ({rate}% on subtotal)"
            else:
                tax_label = "Tax (on subtotal)"
    except Exception:
        # keep default tax_label on any error
        pass
    subtotal = getattr(document, 'subtotal', 0)
    tax_amount = getattr(document, 'tax_amount', 0)
    discount = getattr(document, 'discount_amount', 0)
    shipping = getattr(document, 'shipping_cost', 0)
    total = getattr(document, 'total', 0)
    amount_paid = getattr(document, 'amount_paid', 0)
    balance_due = getattr(document, 'balance_due', 0)

    rows = [
        [Paragraph('Subtotal:', label_style), Paragraph(f"KES {subtotal:,.2f}", label_style)],
        [Paragraph(f"{tax_label}:", label_style), Paragraph(f"KES {tax_amount:,.2f}", label_style)],
    ]

    if discount and discount > 0:
        rows.append([Paragraph('Discount:', label_style), Paragraph(f"-KES {discount:,.2f}", label_style)])
    if shipping and shipping > 0:
        rows.append([Paragraph('Shipping:', label_style), Paragraph(f"KES {shipping:,.2f}", label_style)])

    rows.append([Paragraph('TOTAL:', label_bold_style), Paragraph(f"KES {total:,.2f}", label_bold_style)])
    # only include amount paid/balance if on the document
    if hasattr(document, 'amount_paid'):
        rows.append([Paragraph('Amount Paid:', label_bold_style), Paragraph(f"KES {amount_paid:,.2f}", label_bold_style)])
    if hasattr(document, 'balance_due'):
        rows.append([Paragraph('Balance Due:', label_bold_style), Paragraph(f"KES {balance_due:,.2f}", label_bold_style)])

    tbl = Table(rows, colWidths=[4.5*inch, 2.5*inch])
    tbl.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -2), 'Helvetica', 10),
        ('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 11),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#2563eb')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fef3c7')),
    ]))
    return tbl


def generate_invoice_pdf(invoice, company_info=None, document_type='invoice'):
    """
    Generate professional invoice PDF
    
    Args:
        invoice: Invoice model instance
        company_info: dict with company details (logo_path, name, address, etc.)
    
    Returns:
        bytes: PDF document content
    """
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=A4, 
            topMargin=0.5*inch, 
            bottomMargin=0.5*inch,
            leftMargin=0.75*inch,
            rightMargin=0.75*inch
        )
        elements = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'InvoiceTitle',
            parent=styles['Heading1'],
            fontSize=28,
            textColor=colors.HexColor('#2563eb'),  # Blue
            spaceAfter=5,
            alignment=TA_CENTER
        )
        
        header_style = ParagraphStyle(
            'Header',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#374151'),
        )
        
        # Company Header: use imported helper function for logo
        logo = _get_logo_image(company_info)
        
        # Document title (left) and logo (right)
        title_text = 'INVOICE'
        if document_type == 'packing_slip':
            title_text = 'PACKING SLIP'
        elif document_type == 'delivery_note':
            title_text = 'DELIVERY NOTE'

        # Resolve logo and company info (prefer passed company_info)
        company_info = company_info or _resolve_company_from_document(invoice)
        logo = _get_logo_image(company_info)

        header_row = [Paragraph(title_text, title_style), logo if logo else '']
        header_table = Table([header_row], colWidths=[4.5*inch, 2*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT')
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.2*inch))

        # Build boxed company (left) and document details (right)
        comp_details = _build_company_details_section(company_info)
        company_box = BoxedSection(comp_details, width=4.5*inch)

        # Client details
        client_addr = getattr(invoice, 'billing_address', None) or getattr(invoice, 'shipping_address', None)
        client_info = {
            'name': get_customer_name(invoice),
            'email': get_customer_email(invoice),
            'phone': get_customer_phone(invoice)
        }
        if client_addr:
            client_info.update({
                'floor_number': getattr(client_addr, 'floor_number', ''),
                'building_name': getattr(client_addr, 'building_name', ''),
                'street_name': getattr(client_addr, 'street_name', ''),
                'city': getattr(client_addr, 'city', '')
            })
        client_section = _build_client_details_section(client_info, 'invoice')
        client_box = BoxedSection(client_section, width=4.5*inch)

        # Document details (right)
        doc_info = {
            'type': 'Invoice',
            'number': getattr(invoice, 'invoice_number', ''),
            'date': getattr(invoice, 'invoice_date', None).strftime('%d/%m/%Y') if getattr(invoice, 'invoice_date', None) else '',
            'due_date': getattr(invoice, 'due_date', None).strftime('%d/%m/%Y') if getattr(invoice, 'due_date', None) else ''
        }
        doc_details = _build_document_details_section(doc_info, 'invoice')
        doc_box = BoxedSection(doc_details, width=2*inch)

        # Layout company/client (left stacked) and document details (right)
        left_col = [company_box, Spacer(1, 0.15*inch), client_box]
        left_table = Table([[left_col, doc_box]], colWidths=[4.5*inch, 2*inch])
        # Note: left_col is a list of flowables; wrap in Table cell as-is
        left_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        elements.append(left_table)
        elements.append(Spacer(1, 0.25*inch))
        
        # Invoice Title (supports packing_slip/delivery_note)
        title_text = 'INVOICE'
        if document_type == 'packing_slip':
            title_text = 'PACKING SLIP'
        elif document_type == 'delivery_note':
            title_text = 'DELIVERY NOTE'

        elements.append(Paragraph(title_text, title_style))
        elements.append(Spacer(1, 0.2*inch))

        # If invoice is overdue, draw an orange ribbon on the top-left
        try:
            from reportlab.platypus import Flowable

            class OverdueRibbon(Flowable):
                def __init__(self, text='Overdue'):
                    super().__init__()
                    self.text = text
                    self.width = 1*inch
                    self.height = 1*inch

                def draw(self):
                    c = self.canv
                    c.saveState()
                    # draw rotated rectangle with text
                    c.translate(45, 720)
                    c.rotate(-45)
                    c.setFillColor(colors.HexColor('#f59e0b'))
                    c.rect(0, 0, 180, 30, fill=1, stroke=0)
                    c.setFillColor(colors.white)
                    c.setFont('Helvetica-Bold', 10)
                    c.drawString(10, 8, self.text)
                    c.restoreState()

            if getattr(invoice, 'due_date', None):
                from django.utils import timezone
                if invoice.due_date < timezone.now().date() and invoice.status not in ['paid', 'cancelled', 'void']:
                    elements.insert(0, OverdueRibbon('Overdue'))
        except Exception:
            pass
        
        # Invoice & Customer Details (Two columns)
        # Use Paragraphs for cells so inline HTML (e.g., <b>) is rendered correctly
        label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))
        label_bold_style = ParagraphStyle('LabelBold', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))
        label_bold_style.fontName = 'Helvetica-Bold'

        details_data = [
            [Paragraph('Invoice Number:', label_bold_style), Paragraph(str(invoice.invoice_number), label_style), Paragraph('Bill To:', label_bold_style), Paragraph(get_customer_name(invoice), label_style)],
            [Paragraph('Invoice Date:', label_bold_style), Paragraph(_format_date_safe(getattr(invoice, 'invoice_date', None)), label_style), Paragraph('Email:', label_bold_style), Paragraph(get_customer_email(invoice), label_style)],
            [Paragraph('Due Date:', label_bold_style), Paragraph(_format_date_safe(getattr(invoice, 'due_date', None)), label_style), Paragraph('Phone:', label_bold_style), Paragraph(get_customer_phone(invoice), label_style)],
            [Paragraph('Payment Terms:', label_bold_style), Paragraph(invoice.get_payment_terms_display(), label_style), '', ''],
        ]
        
        details_table = Table(details_data, colWidths=[1.5*inch, 2*inch, 1*inch, 2.5*inch])
        details_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
            ('ALIGN', (0, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.4*inch))
        
        # Line Items Table
        items_data = [[
            Paragraph('#', header_style),
            Paragraph('Description', header_style),
            Paragraph('Qty', header_style),
            Paragraph('Unit Price', header_style),
            Paragraph('Tax', header_style),
            Paragraph('Amount', header_style)
        ]]
        
        for idx, item in enumerate(invoice.items.all(), 1):
            # sanitize name/description to remove embedded HTML
            name = _sanitize_text_for_pdf(getattr(item, 'name', '') or '')
            desc_text = _sanitize_text_for_pdf(getattr(item, 'description', '') or '')
            # Build description with preserved simple formatting (line breaks converted to <br/>)
            desc = f"<b>{name}</b>"
            if desc_text:
                desc += '<br/>' + desc_text.replace('\n', '<br/>')
            qty = getattr(item, 'quantity', 1)
            unit_price = getattr(item, 'unit_price', 0)
            tax_amount = getattr(item, 'tax_amount', 0)
            total_amount = getattr(item, 'total_price', None) or getattr(item, 'total', 0) or (qty * unit_price)

            items_data.append([
                Paragraph(str(idx), header_style),
                Paragraph(desc, header_style),
                Paragraph(str(qty), header_style),
                Paragraph(f"KES {unit_price:,.2f}", header_style),
                Paragraph(f"KES {tax_amount:,.2f}", header_style),
                Paragraph(f"KES {total_amount:,.2f}", header_style)
            ])
        
        items_table = Table(items_data, colWidths=[0.4*inch, 3*inch, 0.7*inch, 1.2*inch, 0.7*inch, 1.2*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUND', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')])
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Totals Section (Right-aligned)
        tax_label = getattr(invoice, 'tax_type', None) or 'Tax'
        totals_data = [
            [Paragraph('Subtotal:', label_style), Paragraph(f"KES {invoice.subtotal:,.2f}", label_style)],
            [Paragraph(f"{tax_label}:", label_style), Paragraph(f"KES {invoice.tax_amount:,.2f}", label_style)],
        ]
        
        if invoice.discount_amount > 0:
            totals_data.append([Paragraph('Discount:', label_style), Paragraph(f"-KES {invoice.discount_amount:,.2f}", label_style)])
        
        if invoice.shipping_cost > 0:
            totals_data.append([Paragraph('Shipping:', label_style), Paragraph(f"KES {invoice.shipping_cost:,.2f}", label_style)])
        
        totals_data.append([Paragraph('TOTAL:', label_bold_style), Paragraph(f"KES {invoice.total:,.2f}", label_bold_style)])
        totals_data.append([Paragraph('Amount Paid:', label_bold_style), Paragraph(f"KES {invoice.amount_paid:,.2f}", label_bold_style)])
        totals_data.append([Paragraph('Balance Due:', label_bold_style), Paragraph(f"KES {invoice.balance_due:,.2f}", label_bold_style)])
        
        totals_table = _build_totals_table(invoice, 'invoice', label_style, label_bold_style)
        elements.append(totals_table)
        
        # Notes
        if invoice.customer_notes:
            elements.append(Spacer(1, 0.3*inch))
            notes_style = ParagraphStyle(
                'Notes',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#6b7280'),
                leftIndent=0.2*inch
            )
            elements.append(Paragraph("<b>Notes:</b>", header_style))
            elements.append(Spacer(1, 0.1*inch))
            sanitized_notes = _sanitize_text_for_pdf(invoice.customer_notes)
            elements.append(Paragraph(sanitized_notes.replace('\n', '<br/>'), notes_style))
        
        # Terms & Conditions
        if invoice.terms_and_conditions:
            elements.append(Spacer(1, 0.2*inch))
            elements.append(Paragraph("<b>Terms & Conditions:</b>", header_style))
            elements.append(Spacer(1, 0.1*inch))
            tc_style = ParagraphStyle(
                'TC',
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.HexColor('#6b7280'),
                leftIndent=0.2*inch
            )
            sanitized_tc = _sanitize_text_for_pdf(invoice.terms_and_conditions)
            elements.append(Paragraph(sanitized_tc.replace('\n', '<br/>'), tc_style))

        # Prepared / Approved signature block
        elements.append(Spacer(1, 0.2*inch))
        prepared_by = getattr(invoice, 'created_by', None)
        approved_by = getattr(invoice, 'approved_by', None)
        sig = _build_signature_table(prepared_by, approved_by, header_style, prepared_date=getattr(invoice, 'created_at', None), approved_date=getattr(invoice, 'approved_at', None))
        elements.append(sig)
        
        # Footer
        elements.append(Spacer(1, 0.4*inch))
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER
        )
        elements.append(Paragraph("Thank you for your business!", footer_style))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}", footer_style))
        
        # Build PDF
        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        logger.info(f"Generated invoice PDF for {invoice.invoice_number}")
        return pdf_bytes
        
    except Exception as e:
        logger.error(f"Error generating invoice PDF: {str(e)}", exc_info=True)
        raise


def generate_quotation_pdf(quotation, company_info=None):
    """
    Generate professional quotation PDF
    
    Args:
        quotation: Quotation model instance
        company_info: dict with company details
    
    Returns:
        bytes: PDF document content
    """
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=A4, 
            topMargin=0.5*inch, 
            bottomMargin=0.5*inch,
            leftMargin=0.75*inch,
            rightMargin=0.75*inch
        )
        elements = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'QuoteTitle',
            parent=styles['Heading1'],
            fontSize=28,
            textColor=colors.HexColor('#059669'),  # Green
            spaceAfter=5,
            alignment=TA_CENTER
        )
        
        header_style = ParagraphStyle(
            'Header',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#374151'),
        )
        
        # Company Header
        if company_info and company_info.get('logo_path'):
            try:
                logo = Image(company_info['logo_path'], width=2*inch, height=1*inch)
                elements.append(logo)
                elements.append(Spacer(1, 0.2*inch))
            except:
                pass
        
        # Prepare company_text but do not append it here - header_table will render
        company_text = ''
        if company_info:
            company_text = f"<b>{company_info.get('name', 'Company Name')}</b><br/>{company_info.get('address', '')}<br/>Email: {company_info.get('email', '')}<br/>Phone: {company_info.get('phone', '')}"
        
        # Quotation Title (use same branding color as invoices)
        # Use invoice blue for consistent branding
        title_style.textColor = colors.HexColor('#2563eb')
        elements.append(Paragraph("QUOTATION", title_style))
        elements.append(Spacer(1, 0.2*inch))

        # Header: title (left) and logo (right)
        title_style.textColor = colors.HexColor('#2563eb')
        title_text = 'QUOTATION'
        logo = _get_logo_image(company_info)
        header_row = [Paragraph(title_text, title_style), logo if logo else '']
        header_table = Table([header_row], colWidths=[4.5*inch, 2*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT')
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.2*inch))

        # Company box (left) and document details box (right)
        company_info = company_info or _resolve_company_from_document(quotation)
        comp_details = _build_company_details_section(company_info)
        company_box = BoxedSection(comp_details, width=4.5*inch)

        client_addr = getattr(quotation, 'billing_address', None) or getattr(quotation, 'shipping_address', None)
        client_info = {
            'name': get_customer_name(quotation),
            'email': get_customer_email(quotation),
            'phone': get_customer_phone(quotation)
        }
        if client_addr:
            client_info.update({
                'floor_number': getattr(client_addr, 'floor_number', ''),
                'building_name': getattr(client_addr, 'building_name', ''),
                'street_name': getattr(client_addr, 'street_name', ''),
                'city': getattr(client_addr, 'city', '')
            })
        client_section = _build_client_details_section(client_info, 'quotation')
        client_box = BoxedSection(client_section, width=4.5*inch)

        doc_info = {
            'type': 'Quotation',
            'number': getattr(quotation, 'quotation_number', ''),
            'date': getattr(quotation, 'quotation_date', None).strftime('%d/%m/%Y') if getattr(quotation, 'quotation_date', None) else '',
            'valid_until': getattr(quotation, 'valid_until', None).strftime('%d/%m/%Y') if getattr(quotation, 'valid_until', None) else '',
            'rfq_number': getattr(quotation, 'rfq_number', ''),
            'tender_quotation_ref': getattr(quotation, 'tender_quotation_ref', '')
        }
        doc_details = _build_document_details_section(doc_info, 'quotation')
        doc_box = BoxedSection(doc_details, width=2*inch)

        left_col = [company_box, Spacer(1, 0.15*inch), client_box]
        left_table = Table([[left_col, doc_box]], colWidths=[4.5*inch, 2*inch])
        left_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        elements.append(left_table)
        elements.append(Spacer(1, 0.25*inch))

        # Quotation & Customer Details - reuse label styles
        label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))
        label_bold_style = ParagraphStyle('LabelBold', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))
        label_bold_style.fontName = 'Helvetica-Bold'

        details_data = [
            [Paragraph('Quotation Number:', label_bold_style), Paragraph(str(quotation.quotation_number), label_style), Paragraph('For:', label_bold_style), Paragraph(get_customer_name(quotation), label_style)],
            [Paragraph('Date:', label_bold_style), Paragraph(quotation.quotation_date.strftime('%d/%m/%Y'), label_style), Paragraph('Email:', label_bold_style), Paragraph(get_customer_email(quotation), label_style)],
            [Paragraph('Valid Until:', label_bold_style), Paragraph(quotation.valid_until.strftime('%d/%m/%Y'), label_style), Paragraph('Phone:', label_bold_style), Paragraph(get_customer_phone(quotation), label_style)],
        ]

        details_table = Table(details_data, colWidths=[1.5*inch, 2*inch, 1*inch, 2.5*inch])
        details_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
            ('ALIGN', (0, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.3*inch))

        # Debug: Log customer info used for the PDF to help investigate mismatches
        try:
            cust = getattr(quotation, 'customer', None)
            if cust:
                logger.debug(f"Generating quotation PDF: quotation_id={quotation.id}, customer_id={getattr(cust,'id',None)}, customer_name={getattr(cust,'business_name',None) or getattr(cust.user,'first_name',None) or getattr(cust.user,'username',None)}")
            else:
                logger.debug(f"Generating quotation PDF: quotation_id={quotation.id}, no customer set")
        except Exception:
            logger.debug(f"Generating quotation PDF: quotation_id={quotation.id}, error reading customer info")
        
        # Introduction
        if quotation.introduction:
            intro_style = ParagraphStyle(
                'Intro',
                parent=styles['Normal'],
                fontSize=10,
                textColor=colors.HexColor('#4b5563'),
                spaceAfter=10
            )
            elements.append(Paragraph(quotation.introduction, intro_style))
            elements.append(Spacer(1, 0.2*inch))
        
        # Line Items Table
        items_data = [[
            Paragraph('#', header_style),
            Paragraph('Description', header_style),
            Paragraph('Qty', header_style),
            Paragraph('Unit Price', header_style),
            Paragraph('Tax', header_style),
            Paragraph('Amount', header_style)
        ]]
        
        for idx, item in enumerate(quotation.items.all(), 1):
            # Build description and numeric fields defensively. OrderItem model does not
            # necessarily include tax_rate/tax_amount fields, so use getattr with fallbacks
            name = _sanitize_text_for_pdf(getattr(item, 'name', '') or '')
            desc_text = _sanitize_text_for_pdf(getattr(item, 'description', '') or '')
            desc = f"<b>{name}</b>"
            if desc_text:
                desc += '<br/>' + desc_text.replace('\n', '<br/>')

            qty = getattr(item, 'quantity', 1) or 1
            unit_price = getattr(item, 'unit_price', 0) or 0

            # Determine tax amount: prefer explicit field, otherwise infer from totals
            tax_amount = getattr(item, 'tax_amount', None)
            total_price_field = getattr(item, 'total_price', None) or getattr(item, 'total', None)
            try:
                if tax_amount is None:
                    if total_price_field is not None:
                        tax_amount = float(total_price_field) - (float(unit_price) * float(qty))
                    else:
                        tax_amount = 0
                tax_amount = float(tax_amount)
            except Exception:
                tax_amount = 0

            # Total amount - prefer explicit field, else compute
            if total_price_field is None:
                total_amount = float(unit_price) * float(qty) + tax_amount
            else:
                total_amount = float(total_price_field)

            items_data.append([
                Paragraph(str(idx), header_style),
                Paragraph(desc, header_style),
                Paragraph(str(qty), header_style),
                Paragraph(f"KES {float(unit_price):,.2f}", header_style),
                Paragraph(f"KES {tax_amount:,.2f}", header_style),
                Paragraph(f"KES {total_amount:,.2f}", header_style)
            ])
        items_table = Table(items_data, colWidths=[0.4*inch, 3.3*inch, 0.7*inch, 1.0*inch, 0.6*inch, 1.2*inch], repeatRows=1)
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUND', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
            ('LEFTPADDING', (1, 0), (1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'TOP')
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Totals Section
        totals_table = _build_totals_table(quotation, 'quotation', label_style, label_bold_style)
        elements.append(totals_table)
        
        # Notes
        if quotation.customer_notes:
            elements.append(Spacer(1, 0.3*inch))
            notes_style = ParagraphStyle(
                'Notes',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#6b7280'),
                leftIndent=0.2*inch
            )
            elements.append(Paragraph("<b>Notes:</b>", header_style))
            elements.append(Spacer(1, 0.1*inch))
            elements.append(Paragraph(quotation.customer_notes, notes_style))
        
        # Terms & Conditions
        if quotation.terms_and_conditions:
            elements.append(Spacer(1, 0.2*inch))
            elements.append(Paragraph("<b>Terms & Conditions:</b>", header_style))
            elements.append(Spacer(1, 0.1*inch))
            tc_style = ParagraphStyle(
                'TC',
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.HexColor('#6b7280'),
                leftIndent=0.2*inch
            )
            elements.append(Paragraph(quotation.terms_and_conditions, tc_style))
        
        # Prepared / Approved signature block for quotation
        elements.append(Spacer(1, 0.2*inch))
        prepared_by = getattr(quotation, 'created_by', None)
        approved_by = getattr(quotation, 'approved_by', None)
        sig = _build_signature_table(prepared_by, approved_by, header_style, prepared_date=getattr(quotation, 'created_at', None), approved_date=getattr(quotation, 'approved_at', None))
        elements.append(sig)

        # Footer
        elements.append(Spacer(1, 0.4*inch))
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER
        )
        validity_text = f"This quotation is valid until {quotation.valid_until.strftime('%d/%m/%Y')}"
        elements.append(Paragraph(validity_text, footer_style))
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph("Thank you for your interest in our services!", footer_style))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}", footer_style))
        
        # Build PDF
        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        logger.info(f"Generated quotation PDF for {quotation.quotation_number}")
        return pdf_bytes
        
    except Exception as e:
        logger.error(f"Error generating quotation PDF: {str(e)}", exc_info=True)
        raise

