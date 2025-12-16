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
logger = logging.getLogger(__name__)
from django.conf import settings
import re
import html
try:
    from django.contrib.staticfiles import finders
except Exception:
    finders = None


def _sanitize_text_for_pdf(text):
    """
    Sanitize HTML-ish text for PDF output.
    Returns plain text with newlines preserved.
    """
    try:
        if not text:
            return ''

        # Convert bytes to str if necessary
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='ignore')

        # Normalize common block separators to newlines
        text = re.sub(r'</p\s*>', '\n\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

        # Strip remaining tags
        text = re.sub(r'<[^>]+>', '', text)

        # Unescape HTML entities (e.g., &nbsp;, &amp;)
        text = html.unescape(text)

        # Replace multiple newlines with at most two
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()
    except Exception:
        return str(text)


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
        
        # Company Header: attempt to resolve logo path (business logo or default static)
        logo_path = None
        if company_info and company_info.get('logo_path'):
            candidate = company_info.get('logo_path')
            # If candidate is a filesystem path and exists, use it
            if isinstance(candidate, str) and os.path.exists(candidate):
                logo_path = candidate
            else:
                # Try staticfiles finders to resolve relative/static paths
                if finders:
                    found = finders.find(candidate.lstrip('/')) or finders.find('logo/logo.png')
                    logo_path = found
                else:
                    # Fallback to trying BASE_DIR + candidate
                    try:
                        potential = os.path.join(settings.BASE_DIR, candidate.lstrip('/'))
                        if os.path.exists(potential):
                            logo_path = potential
                    except Exception:
                        logo_path = None

        # If still not found, try to locate default logo in static
        if not logo_path:
            try:
                if finders:
                    logo_path = finders.find('logo/logo.png') or finders.find('static/logo/logo.png')
                else:
                    candidate = os.path.join(settings.BASE_DIR, 'static', 'logo', 'logo.png')
                    if os.path.exists(candidate):
                        logo_path = candidate
            except Exception:
                logo_path = None

        if logo_path:
            try:
                # Position logo to the right of company details
                logo = Image(logo_path, width=2*inch, height=1*inch)
            except Exception:
                logo = None
            except Exception:
                pass
        
        # Company details
        # Layout company details and logo side-by-side
        if company_info or logo:
            company_text = ''
            if company_info:
                company_text = f"<b>{company_info.get('name', 'Company Name')}</b><br/>"
                company_text += f"{company_info.get('address', '')}<br/>"
                company_text += f"Email: {company_info.get('email', '')}<br/>"
                company_text += f"Phone: {company_info.get('phone', '')}"

            # Two-column table: details (left), logo (right)
            row = [Paragraph(company_text, header_style) if company_text else '', logo if logo else '']
            header_table = Table([row], colWidths=[4.5*inch, 2*inch])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT')
            ]))
            elements.append(header_table)
            elements.append(Spacer(1, 0.3*inch))
        
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
            [Paragraph('Invoice Date:', label_bold_style), Paragraph(invoice.invoice_date.strftime('%d/%m/%Y'), label_style), Paragraph('Email:', label_bold_style), Paragraph(get_customer_email(invoice), label_style)],
            [Paragraph('Due Date:', label_bold_style), Paragraph(invoice.due_date.strftime('%d/%m/%Y'), label_style), Paragraph('Phone:', label_bold_style), Paragraph(get_customer_phone(invoice), label_style)],
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
        items_data = [['#', 'Description', 'Qty', 'Unit Price', 'Tax', 'Amount']]
        
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
                str(idx),
                Paragraph(desc, header_style),
                str(qty),
                f"KES {unit_price:,.2f}",
                f"KES {tax_amount:,.2f}",
                f"KES {total_amount:,.2f}"
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
        totals_data = [
            [Paragraph('Subtotal:', label_style), Paragraph(f"KES {invoice.subtotal:,.2f}", label_style)],
            [Paragraph('Tax:', label_style), Paragraph(f"KES {invoice.tax_amount:,.2f}", label_style)],
        ]
        
        if invoice.discount_amount > 0:
            totals_data.append([Paragraph('Discount:', label_style), Paragraph(f"-KES {invoice.discount_amount:,.2f}", label_style)])
        
        if invoice.shipping_cost > 0:
            totals_data.append([Paragraph('Shipping:', label_style), Paragraph(f"KES {invoice.shipping_cost:,.2f}", label_style)])
        
        totals_data.append([Paragraph('TOTAL:', label_bold_style), Paragraph(f"KES {invoice.total:,.2f}", label_bold_style)])
        totals_data.append([Paragraph('Amount Paid:', label_bold_style), Paragraph(f"KES {invoice.amount_paid:,.2f}", label_bold_style)])
        totals_data.append([Paragraph('Balance Due:', label_bold_style), Paragraph(f"KES {invoice.balance_due:,.2f}", label_bold_style)])
        
        totals_table = Table(totals_data, colWidths=[4.5*inch, 2.5*inch])
        totals_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -2), 'Helvetica', 10),
            ('FONT', (0, -3), (-1, -1), 'Helvetica-Bold', 11),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LINEABOVE', (0, -3), (-1, -3), 2, colors.HexColor('#2563eb')),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fef3c7')),
        ]))
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
        
        # Company details
        if company_info:
            company_text = f"<b>{company_info.get('name', 'Company Name')}</b><br/>"
            company_text += f"{company_info.get('address', '')}<br/>"
            company_text += f"Email: {company_info.get('email', '')}<br/>"
            company_text += f"Phone: {company_info.get('phone', '')}"
            elements.append(Paragraph(company_text, header_style))
            elements.append(Spacer(1, 0.3*inch))
        
        # Quotation Title
        elements.append(Paragraph("QUOTATION", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Quotation & Customer Details
        # Quotation details (use Paragraphs to avoid raw HTML showing in PDF)
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
        items_data = [['#', 'Description', 'Qty', 'Unit Price', 'Tax', 'Amount']]
        
        for idx, item in enumerate(quotation.items.all(), 1):
            desc = f"<b>{item.name}</b><br/>{item.description}" if item.description else item.name
            items_data.append([
                str(idx),
                Paragraph(desc, header_style),
                str(item.quantity),
                f"KES {item.unit_price:,.2f}",
                f"{item.tax_rate}%",
                f"KES {item.total:,.2f}"
            ])
        
        items_table = Table(items_data, colWidths=[0.4*inch, 3*inch, 0.7*inch, 1.2*inch, 0.7*inch, 1.2*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#059669')),
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
            ('ROWBACKGROUND', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0fdf4')])
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Totals Section
        totals_data = [
            ['Subtotal:', f"KES {quotation.subtotal:,.2f}"],
            ['Tax:', f"KES {quotation.tax_amount:,.2f}"],
        ]
        
        if quotation.discount_amount > 0:
            totals_data.append(['Discount:', f"-KES {quotation.discount_amount:,.2f}"])
        
        if quotation.shipping_cost > 0:
            totals_data.append(['Shipping:', f"KES {quotation.shipping_cost:,.2f}"])
        
        totals_data.append(['<b>TOTAL:</b>', f"<b>KES {quotation.total:,.2f}</b>"])
        
        totals_table = Table(totals_data, colWidths=[4.5*inch, 2.5*inch])
        totals_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -2), 'Helvetica', 10),
            ('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 12),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#059669')),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#d1fae5')),
        ]))
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


def get_customer_name(doc):
    """Get customer name from document"""
    try:
        customer = doc.customer
        if customer.business_name:
            return customer.business_name
        return f"{customer.user.first_name} {customer.user.last_name}".strip()
    except:
        return "N/A"


def get_customer_email(doc):
    """Get customer email from document"""
    try:
        return doc.customer.user.email
    except:
        return "N/A"


def get_customer_phone(doc):
    """Get customer phone from document"""
    try:
        return doc.customer.user.phone or "N/A"
    except:
        return "N/A"

