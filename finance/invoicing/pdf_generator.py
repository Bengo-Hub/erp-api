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

logger = logging.getLogger(__name__)


def generate_invoice_pdf(invoice, company_info=None):
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
        
        # Invoice Title
        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Invoice & Customer Details (Two columns)
        details_data = [
            ['<b>Invoice Number:</b>', invoice.invoice_number, '<b>Bill To:</b>', get_customer_name(invoice)],
            ['<b>Invoice Date:</b>', invoice.invoice_date.strftime('%d/%m/%Y'), '<b>Email:</b>', get_customer_email(invoice)],
            ['<b>Due Date:</b>', invoice.due_date.strftime('%d/%m/%Y'), '<b>Phone:</b>', get_customer_phone(invoice)],
            ['<b>Payment Terms:</b>', invoice.get_payment_terms_display(), '', ''],
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
            ['Subtotal:', f"KES {invoice.subtotal:,.2f}"],
            ['Tax:', f"KES {invoice.tax_amount:,.2f}"],
        ]
        
        if invoice.discount_amount > 0:
            totals_data.append(['Discount:', f"-KES {invoice.discount_amount:,.2f}"])
        
        if invoice.shipping_cost > 0:
            totals_data.append(['Shipping:', f"KES {invoice.shipping_cost:,.2f}"])
        
        totals_data.append(['<b>TOTAL:</b>', f"<b>KES {invoice.total:,.2f}</b>"])
        totals_data.append(['<b>Amount Paid:</b>', f"<b>KES {invoice.amount_paid:,.2f}</b>"])
        totals_data.append(['<b>Balance Due:</b>', f"<b>KES {invoice.balance_due:,.2f}</b>"])
        
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
            elements.append(Paragraph(invoice.customer_notes, notes_style))
        
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
            elements.append(Paragraph(invoice.terms_and_conditions, tc_style))
        
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
        details_data = [
            ['<b>Quotation Number:</b>', quotation.quotation_number, '<b>For:</b>', get_customer_name(quotation)],
            ['<b>Date:</b>', quotation.quotation_date.strftime('%d/%m/%Y'), '<b>Email:</b>', get_customer_email(quotation)],
            ['<b>Valid Until:</b>', quotation.valid_until.strftime('%d/%m/%Y'), '<b>Phone:</b>', get_customer_phone(quotation)],
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

