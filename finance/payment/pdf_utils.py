"""
PDF generation utilities for finance invoices and receipts.
Uses reportlab for PDF generation.
"""
from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def generate_invoice_pdf(invoice_data):
    """
    Generate PDF for an invoice using reportlab.
    
    Args:
        invoice_data: dict with keys:
            - invoice_number: str
            - invoice_date: date
            - customer_name: str
            - customer_email: str
            - items: list of {description, quantity, unit_price, total}
            - subtotal: Decimal
            - tax: Decimal
            - total: Decimal
            - notes: str (optional)
    
    Returns:
        bytes: PDF document content
    """
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()
        
        # Header
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=10
        )
        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Spacer(1, 0.3*inch))
        
        # Invoice details
        details_data = [
            ['Invoice Number:', invoice_data.get('invoice_number', 'N/A')],
            ['Invoice Date:', invoice_data.get('invoice_date', 'N/A')],
            ['Customer:', invoice_data.get('customer_name', 'N/A')],
        ]
        details_table = Table(details_data, colWidths=[2*inch, 4*inch])
        details_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Line items
        items = invoice_data.get('items', [])
        items_data = [['Description', 'Quantity', 'Unit Price', 'Total']]
        for item in items:
            items_data.append([
                item.get('description', ''),
                str(item.get('quantity', 0)),
                f"KES {item.get('unit_price', 0):.2f}",
                f"KES {item.get('total', 0):.2f}"
            ])
        
        items_table = Table(items_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Totals
        totals_data = [
            ['Subtotal:', f"KES {invoice_data.get('subtotal', 0):.2f}"],
            ['Tax:', f"KES {invoice_data.get('tax', 0):.2f}"],
            ['TOTAL:', f"KES {invoice_data.get('total', 0):.2f}"]
        ]
        totals_table = Table(totals_data, colWidths=[4.5*inch, 1.5*inch])
        totals_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 11),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.grey),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 12),
        ]))
        elements.append(totals_table)
        
        # Notes
        if invoice_data.get('notes'):
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph("<b>Notes:</b>", styles['Normal']))
            elements.append(Paragraph(invoice_data.get('notes'), styles['Normal']))
        
        # Build PDF
        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        logger.info(f"Generated invoice PDF for invoice {invoice_data.get('invoice_number')}")
        return pdf_bytes
        
    except Exception as e:
        logger.error(f"Error generating invoice PDF: {str(e)}", exc_info=True)
        raise


def generate_receipt_pdf(receipt_data):
    """
    Generate PDF for a receipt using reportlab.
    
    Args:
        receipt_data: dict with keys:
            - receipt_number: str
            - receipt_date: datetime
            - customer_name: str (optional)
            - items: list of {description, quantity, unit_price, total}
            - subtotal: Decimal
            - tax: Decimal
            - total: Decimal
            - payment_method: str
    
    Returns:
        bytes: PDF document content
    """
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.4*inch, bottomMargin=0.4*inch)
        elements = []
        styles = getSampleStyleSheet()
        
        # Header
        title_style = ParagraphStyle(
            'ReceiptTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=5
        )
        elements.append(Paragraph("RECEIPT", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Receipt details
        details_data = [
            ['Receipt #:', receipt_data.get('receipt_number', 'N/A')],
            ['Date:', str(receipt_data.get('receipt_date', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'))],
        ]
        if receipt_data.get('customer_name'):
            details_data.append(['Customer:', receipt_data.get('customer_name')])
        
        details_table = Table(details_data, colWidths=[1.5*inch, 3.5*inch])
        details_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.15*inch))
        
        # Line items
        items = receipt_data.get('items', [])
        items_data = [['Item', 'Qty', 'Price', 'Amount']]
        for item in items:
            items_data.append([
                item.get('description', ''),
                str(item.get('quantity', 1)),
                f"KES {item.get('unit_price', 0):.2f}",
                f"KES {item.get('total', 0):.2f}"
            ])
        
        items_table = Table(items_data, colWidths=[2.5*inch, 0.8*inch, 1.2*inch, 1.2*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUND', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.1*inch))
        
        # Totals
        totals_data = [
            ['Subtotal:', f"KES {receipt_data.get('subtotal', 0):.2f}"],
            ['Tax (VAT):', f"KES {receipt_data.get('tax', 0):.2f}"],
            ['TOTAL:', f"KES {receipt_data.get('total', 0):.2f}"]
        ]
        totals_table = Table(totals_data, colWidths=[3.5*inch, 1.5*inch])
        totals_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.grey),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 10),
        ]))
        elements.append(totals_table)
        
        # Payment method
        if receipt_data.get('payment_method'):
            elements.append(Spacer(1, 0.15*inch))
            payment_style = ParagraphStyle(
                'PaymentStyle',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.grey
            )
            elements.append(Paragraph(f"<b>Payment Method:</b> {receipt_data.get('payment_method')}", payment_style))
        
        # Footer
        elements.append(Spacer(1, 0.2*inch))
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=1  # Center
        )
        elements.append(Paragraph("Thank you for your business!", footer_style))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", footer_style))
        
        # Build PDF
        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        logger.info(f"Generated receipt PDF for receipt {receipt_data.get('receipt_number')}")
        return pdf_bytes
        
    except Exception as e:
        logger.error(f"Error generating receipt PDF: {str(e)}", exc_info=True)
        raise


def download_invoice_pdf(invoice_id):
    """
    Download PDF for a specific invoice.
    
    Args:
        invoice_id: int - ID of the invoice to download
    
    Returns:
        bytes: PDF document content
    """
    try:
        # Import here to avoid circular imports
        from finance.payment.models import BillingDocument
        
        invoice = BillingDocument.objects.get(id=invoice_id, document_type='INVOICE')
        
        # Build invoice data from model
        invoice_data = {
            'invoice_number': invoice.document_number,
            'invoice_date': invoice.issue_date,
            'customer_name': str(invoice.customer) if invoice.customer else 'N/A',
            'items': [
                {
                    'description': getattr(item, 'description', ''),
                    'quantity': getattr(item, 'quantity', 1),
                    'unit_price': getattr(item, 'unit_price', 0),
                    'total': getattr(item, 'total', 0)
                }
                for item in getattr(invoice, 'items', [])
            ],
            'subtotal': invoice.subtotal or 0,
            'tax': invoice.tax_amount or 0,
            'total': invoice.total,
            'notes': invoice.notes if hasattr(invoice, 'notes') else ''
        }
        
        return generate_invoice_pdf(invoice_data)
        
    except BillingDocument.DoesNotExist:
        logger.error(f"Invoice {invoice_id} not found")
        raise
    except Exception as e:
        logger.error(f"Error downloading invoice PDF: {str(e)}", exc_info=True)
        raise 