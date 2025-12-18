"""
Professional LPO (Local Purchase Order) PDF Generation using ReportLab
Generates print-ready purchase orders with company branding and supplier details
"""
from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from finance.utils import _get_logo_image, _build_company_details_section, _build_client_details_section, _build_document_details_section, BoxedSection
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from datetime import datetime
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


def generate_lpo_pdf(purchase_order, company_info=None):
    """
    Generate professional LPO (Purchase Order) PDF
    
    Args:
        purchase_order: PurchaseOrder model instance
        company_info: dict with company details (logo_path, name, address, email, phone, etc.)
    
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
            'POTitle',
            parent=styles['Heading1'],
            fontSize=28,
            textColor=colors.HexColor('#1e40af'),  # Dark blue
            spaceAfter=5,
            alignment=TA_CENTER
        )
        
        header_style = ParagraphStyle(
            'Header',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#374151'),
        )
        
        subheader_style = ParagraphStyle(
            'SubHeader',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#1f2937'),
            fontName='Helvetica-Bold'
        )
        
        # Header: title left, logo right
        title_text = 'PURCHASE ORDER (LPO)'
        # Resolve company info from provided info or purchase_order
        company_info = company_info or {'name': 'Your Company Name', 'address': 'Company Address', 'email': 'OuH4P@example.com', 'phone': '123-456-7890', 'pin': '123456789', 'logo': None}
        logo = _get_logo_image(company_info)
        header_row = [Paragraph(title_text, title_style), logo if logo else '']
        header_table = Table([header_row], colWidths=[4.5*inch, 2*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT')
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.15*inch))

        # Company box on left
        comp_details = _build_company_details_section(company_info)
        company_box = BoxedSection(comp_details, width=4.5*inch)
        # Supplier/Client box
        supplier_info = {
            'name': get_supplier_name(purchase_order),
            'email': get_supplier_email(purchase_order),
            'phone': get_supplier_phone(purchase_order)
        }
        supplier_section = _build_client_details_section(supplier_info, 'lpo')
        supplier_box = BoxedSection(supplier_section, width=4.5*inch)

        doc_info = {
            'type': 'LPO',
            'number': getattr(purchase_order, 'order_number', ''),
            'date': getattr(purchase_order, 'order_date', None).strftime('%d/%m/%Y') if getattr(purchase_order, 'order_date', None) else '',
            'expected_delivery': getattr(purchase_order, 'expected_delivery', None).strftime('%d/%m/%Y') if getattr(purchase_order, 'expected_delivery', None) else ''
        }
        doc_details = _build_document_details_section(doc_info, 'lpo')
        doc_box = BoxedSection(doc_details, width=2*inch)

        left_col = [company_box, Spacer(1, 0.15*inch), supplier_box]
        left_table = Table([[left_col, doc_box]], colWidths=[4.5*inch, 2*inch])
        left_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        elements.append(left_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # PO Title
        elements.append(Paragraph("PURCHASE ORDER (LPO)", title_style))
        elements.append(Spacer(1, 0.15*inch))
        
        # PO & Supplier Details (Two columns)
        details_data = [
            ['<b>PO Number:</b>', purchase_order.order_number, '<b>Supplier/Vendor:</b>', get_supplier_name(purchase_order)],
            ['<b>PO Date:</b>', purchase_order.order_date.strftime('%d/%m/%Y') if purchase_order.order_date else '', '<b>Email:</b>', get_supplier_email(purchase_order)],
            ['<b>Expected Delivery:</b>', purchase_order.expected_delivery.strftime('%d/%m/%Y') if purchase_order.expected_delivery else 'N/A', '<b>Phone:</b>', get_supplier_phone(purchase_order)],
            ['<b>Status:</b>', purchase_order.get_status_display() if hasattr(purchase_order, 'get_status_display') else purchase_order.status, '<b>Requisition Ref:</b>', purchase_order.requisition.reference_number if purchase_order.requisition else 'N/A'],
        ]
        
        details_table = Table(details_data, colWidths=[1.3*inch, 1.7*inch, 1.3*inch, 2.2*inch])
        details_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
            ('ALIGN', (0, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Terms & Delivery Section
        if purchase_order.terms or purchase_order.delivery_instructions:
            terms_data = [
                ['<b>Payment Terms:</b>', purchase_order.terms if purchase_order.terms else 'N/A'],
                ['<b>Delivery Instructions:</b>', purchase_order.delivery_instructions if purchase_order.delivery_instructions else 'N/A'],
            ]
            terms_table = Table(terms_data, colWidths=[1.5*inch, 5*inch])
            terms_table.setStyle(TableStyle([
                ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(terms_table)
            elements.append(Spacer(1, 0.2*inch))
        
        # Line Items Table
        items_data = [['#', 'Description', 'Qty', 'Unit Price', 'Amount']]
        
        # Get items from the PurchaseOrder's related model (e.g., line items table)
        try:
            items = purchase_order.items.all() if hasattr(purchase_order, 'items') else []
        except:
            items = []
        
        total_amount = Decimal('0.00')
        for idx, item in enumerate(items, 1):
            # Get description from item or product
            desc = ''
            if hasattr(item, 'product') and item.product:
                desc = item.product.name or item.product.title or ''
            elif hasattr(item, 'description'):
                desc = item.description or ''
            
            # Limit description to first 50 chars
            if len(desc) > 50:
                desc = desc[:47] + '...'
            
            # Get quantity and price
            qty = getattr(item, 'quantity', 1)
            unit_price = getattr(item, 'unit_price', Decimal('0.00'))
            amount = Decimal(qty) * Decimal(unit_price)
            total_amount += amount
            
            items_data.append([
                str(idx),
                Paragraph(desc, header_style),
                str(qty),
                f"KES {unit_price:,.2f}",
                f"KES {amount:,.2f}"
            ])
        
        items_table = Table(items_data, colWidths=[0.4*inch, 3.2*inch, 0.6*inch, 1.1*inch, 1.1*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUND', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')])
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Totals Section (Right-aligned)
        # Tax label should reflect whether tax is applied per-line or on the subtotal
        try:
            if getattr(purchase_order, 'tax_mode', None) == 'on_total':
                rate = getattr(purchase_order, 'tax_rate', None)
                if rate is not None and str(rate) != '':
                    tax_label = f"Tax ({rate}% on subtotal):"
                else:
                    tax_label = "Tax (on subtotal):"
            else:
                tax_label = 'Tax (if any):'
        except Exception:
            tax_label = 'Tax (if any):'

        totals_data = [
            ['Subtotal:', f"KES {total_amount:,.2f}"],
            [tax_label, f"KES {getattr(purchase_order, 'tax_amount', Decimal('0.00')):,.2f}"],
        ]
        
        if hasattr(purchase_order, 'discount') and purchase_order.discount and Decimal(purchase_order.discount) > 0:
            totals_data.append(['Discount:', f"-KES {purchase_order.discount:,.2f}"])
        
        final_total = total_amount + Decimal(getattr(purchase_order, 'tax_amount', Decimal('0.00'))) - Decimal(getattr(purchase_order, 'discount', Decimal('0.00')))
        totals_data.append(['<b>TOTAL:</b>', f"<b>KES {final_total:,.2f}</b>"])
        
        if hasattr(purchase_order, 'approved_budget') and purchase_order.approved_budget:
            totals_data.append(['Approved Budget:', f"KES {purchase_order.approved_budget:,.2f}"])
        
        totals_table = Table(totals_data, colWidths=[4.5*inch, 2*inch])
        totals_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -2), 'Helvetica', 10),
            ('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 11),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#1e40af')),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#dbeafe')),
        ]))
        elements.append(totals_table)
        
        # Notes
        if hasattr(purchase_order, 'notes') and purchase_order.notes:
            elements.append(Spacer(1, 0.25*inch))
            notes_style = ParagraphStyle(
                'Notes',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#6b7280'),
                leftIndent=0.2*inch
            )
            elements.append(Paragraph("<b>Notes:</b>", subheader_style))
            elements.append(Spacer(1, 0.08*inch))
            elements.append(Paragraph(purchase_order.notes, notes_style))
        
        # Footer
        elements.append(Spacer(1, 0.3*inch))
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER
        )
        elements.append(Paragraph("Please confirm receipt and invoice against this PO number.", footer_style))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}", footer_style))
        
        # Build PDF
        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        logger.info(f"Generated LPO PDF for {purchase_order.order_number}")
        return pdf_bytes
        
    except Exception as e:
        logger.error(f"Error generating LPO PDF: {str(e)}", exc_info=True)
        raise


def get_supplier_name(purchase_order):
    """Extract supplier name from PurchaseOrder."""
    if hasattr(purchase_order, 'supplier') and purchase_order.supplier:
        supplier = purchase_order.supplier
        if hasattr(supplier, 'business_name') and supplier.business_name:
            return supplier.business_name
        if hasattr(supplier, 'user') and supplier.user:
            return f"{supplier.user.first_name} {supplier.user.last_name}".strip()
    return 'Not specified'


def get_supplier_email(purchase_order):
    """Extract supplier email from PurchaseOrder."""
    if hasattr(purchase_order, 'supplier') and purchase_order.supplier:
        supplier = purchase_order.supplier
        if hasattr(supplier, 'user') and supplier.user and supplier.user.email:
            return supplier.user.email
    return ''


def get_supplier_phone(purchase_order):
    """Extract supplier phone from PurchaseOrder."""
    if hasattr(purchase_order, 'supplier') and purchase_order.supplier:
        supplier = purchase_order.supplier
        if hasattr(supplier, 'phone') and supplier.phone:
            return supplier.phone
    return ''
