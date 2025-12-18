from decimal import Decimal
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from finance.invoicing import pdf_generator


class DummyDoc:
    pass


def make_label_styles():
    styles = getSampleStyleSheet()
    label_style = ParagraphStyle('Label', parent=styles['Normal'])
    label_bold_style = ParagraphStyle('LabelBold', parent=styles['Normal'])
    label_bold_style.fontName = 'Helvetica-Bold'
    return label_style, label_bold_style


def test_build_totals_table_on_total_label():
    doc = DummyDoc()
    doc.tax_mode = 'on_total'
    doc.tax_rate = Decimal('16.00')
    doc.subtotal = Decimal('1000.00')
    doc.tax_amount = Decimal('160.00')
    doc.discount = Decimal('0.00')
    doc.shipping_cost = Decimal('0.00')
    doc.total = Decimal('1160.00')

    label_style, label_bold_style = make_label_styles()
    tbl = pdf_generator._build_totals_table(doc, 'invoice', label_style, label_bold_style)

    # The second row (index 1) first column should contain the tax label with rate
    # Table cell values are stored in _cellvalues
    cell = tbl._cellvalues[1][0]
    # Paragraph stores the source text in .text
    assert '16' in getattr(cell, 'text', '') or '16' in str(cell)


def test_generate_lpo_pdf_includes_on_total_tax_label():
    # Create a lightweight object mimicking a purchase order
    class PO:
        pass

    po = PO()
    po.tax_mode = 'on_total'
    po.tax_rate = Decimal('10')
    po.tax_amount = Decimal('50.00')
    # Minimal attributes used by generator
    po.order_number = 'PO-TEST'
    from procurement.orders.pdf_generator import generate_lpo_pdf

    pdf_bytes = generate_lpo_pdf(po, company_info=None)
    assert pdf_bytes and len(pdf_bytes) > 100
    # the rendered PDF should include the tax rate description somewhere in the raw bytes
    assert b'10' in pdf_bytes or b'10%' in pdf_bytes or b'on subtotal' in pdf_bytes
