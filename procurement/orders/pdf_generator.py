"""
Professional LPO (Local Purchase Order) PDF Generation using ReportLab
Generates print-ready purchase orders with company branding and supplier details
Supports multiple currencies with proper formatting
"""
from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from finance.utils import _get_logo_image, _build_company_details_section, _build_client_details_section, _build_document_details_section, BoxedSection, get_brand_color
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from datetime import datetime
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

# Currency symbol map for PDF formatting
CURRENCY_SYMBOLS = {
    'KES': 'KSh',
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'UGX': 'USh',
    'TZS': 'TSh',
    'ZAR': 'R',
    'NGN': '₦',
    'GHS': 'GH₵',
    'RWF': 'FRw',
    'ETB': 'Br',
    'AED': 'AED',
    'INR': '₹',
    'CNY': '¥',
    'JPY': '¥'
}


def format_currency_amount(amount, currency_code='KES'):
    """
    Format amount with currency symbol.

    Args:
        amount: Decimal or number to format
        currency_code: ISO currency code (default: KES)

    Returns:
        str: Formatted currency string
    """
    symbol = CURRENCY_SYMBOLS.get(currency_code.upper() if currency_code else 'KES', currency_code or 'KES')
    try:
        value = Decimal(str(amount)) if amount else Decimal('0.00')
    except:
        value = Decimal('0.00')

    # Position symbol before or after based on convention
    if currency_code in ['USD', 'GBP', 'EUR']:
        return f"{symbol}{value:,.2f}"
    else:
        return f"{symbol} {value:,.2f}"


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
        
        # Get currency from purchase order (default to KES)
        currency = getattr(purchase_order, 'currency', 'KES') or 'KES'

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
                format_currency_amount(unit_price, currency),
                format_currency_amount(amount, currency)
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
            ['Subtotal:', format_currency_amount(total_amount, currency)],
            [tax_label, format_currency_amount(getattr(purchase_order, 'tax_amount', Decimal('0.00')), currency)],
        ]

        # Handle discount - check both discount and discount_amount fields
        discount_value = Decimal('0.00')
        if hasattr(purchase_order, 'discount_amount') and purchase_order.discount_amount:
            discount_value = Decimal(str(purchase_order.discount_amount))
        elif hasattr(purchase_order, 'discount') and purchase_order.discount:
            discount_value = Decimal(str(purchase_order.discount))

        if discount_value > 0:
            totals_data.append(['Discount:', f"-{format_currency_amount(discount_value, currency)}"])

        final_total = total_amount + Decimal(getattr(purchase_order, 'tax_amount', Decimal('0.00'))) - discount_value
        totals_data.append(['<b>TOTAL:</b>', f"<b>{format_currency_amount(final_total, currency)}</b>"])

        if hasattr(purchase_order, 'approved_budget') and purchase_order.approved_budget:
            totals_data.append(['Approved Budget:', format_currency_amount(purchase_order.approved_budget, currency)])

        # Show exchange rate if not base currency
        if currency != 'KES' and hasattr(purchase_order, 'exchange_rate') and purchase_order.exchange_rate:
            rate = Decimal(str(purchase_order.exchange_rate))
            if rate != Decimal('1'):
                totals_data.append([f'Exchange Rate ({currency}/KES):', f"{rate:,.6f}"])
        
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
        
        # Create page footer function matching Masterspace format
        def _create_page_footer(canvas, doc_obj, company_info=company_info):
            """Draw footer on each page in Masterspace format."""
            canvas.saveState()

            # Extract company info with fallbacks
            def _ci(key, default=''):
                if company_info:
                    try:
                        return company_info.get(key, default)
                    except Exception:
                        return getattr(company_info, key, default)
                return default

            # Get details for footer
            branch_name = _ci('branch_name') or _ci('address') or '2nd Floor, Ramis Center, Mombasa Road'
            postal_code = _ci('postal_code') or '57935 - 00100'
            city = _ci('city') or 'Nairobi'
            country = _ci('country') or 'Kenya'
            phone1 = _ci('contact_number') or _ci('phone') or '+254 715 857 832'
            phone2 = _ci('alternate_contact_number') or '+254 720 995 917'
            email = _ci('email') or 'info@masterspace.co.ke'
            website = _ci('website') or 'www.masterspace.co.ke'

            # Format phone numbers for display
            def format_phone(p):
                if not p:
                    return ''
                p = str(p).replace('+254', '+254 ')
                if len(p) == 13 and p.startswith('+254 '):
                    return p[:5] + p[5:8] + ' ' + p[8:11] + ' ' + p[11:]
                return p

            phone1_fmt = format_phone(phone1)
            phone2_fmt = format_phone(phone2)
            phone_str = f"T : {phone1_fmt}"
            if phone2_fmt and phone2_fmt != phone1_fmt:
                phone_str += f" / {phone2_fmt}"

            postal_line = f"P.O Box {postal_code}, {city}-{country}."
            brand_color = get_brand_color(company_info or {})

            footer_y = 0.45 * inch
            left_margin = 0.75 * inch
            right_margin = A4[0] - 0.75 * inch
            bar_width = 8

            # Draw blue vertical bar on left
            canvas.setFillColor(brand_color)
            canvas.rect(left_margin, footer_y - 5, bar_width, 45, fill=1, stroke=0)

            text_start = left_margin + bar_width + 8
            canvas.setFillColor(colors.HexColor('#374151'))
            canvas.setFont('Helvetica', 8)

            canvas.drawString(text_start, footer_y + 28, branch_name)
            canvas.drawString(text_start, footer_y + 16, postal_line)
            canvas.drawString(text_start, footer_y + 4, phone_str)

            canvas.setFillColor(brand_color)
            canvas.setFont('Helvetica', 8)
            canvas.drawRightString(right_margin, footer_y + 20, email)
            canvas.setFont('Helvetica-Bold', 8)
            canvas.drawRightString(right_margin, footer_y + 8, website)

            canvas.restoreState()

        # Build PDF with page footer
        doc.build(elements, onFirstPage=_create_page_footer, onLaterPages=_create_page_footer)
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
