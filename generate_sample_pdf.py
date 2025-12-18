#!/usr/bin/env python
"""Quick script to generate a sample invoice PDF for layout testing."""

import os
import sys
# Add the project directory to the Python path (not loading full Django for this simple test)
sys.path.insert(0, os.path.dirname(__file__))

from finance.pdf_generator import generate_invoice_pdf

# Mock invoice object
class MockInvoice:
    def __init__(self):
        self.invoice_number = 'INV-001'
        self.invoice_date = '2025-12-17'
        self.due_date = '2025-12-24'
        self.customer_name = 'Sample Customer Ltd'
        self.customer_email = 'customer@example.com'
        self.customer_phone = '+254700000000'

        # Mock items
        self.items = [
            MockItem('Sample Product 1', 2, 100.00, 16.00, 216.00),
            MockItem('Sample Product 2', 1, 50.00, 8.00, 58.00),
        ]

class MockItem:
    def __init__(self, name, quantity, unit_price, tax_amount, total_price):
        self.name = name
        self.quantity = quantity
        self.unit_price = unit_price
        self.tax_amount = tax_amount
        self.total_price = total_price
        self.tax_type = 'VAT'

# Mock company info
company_info = {
    'name': 'Sample Company Ltd',
    'address': '123 Sample Street, Nairobi, Kenya',
    'email': 'info@samplecompany.com',
    'phone': '+254711111111',
    'pin': 'P051234567890',
    'logo_path': None,  # No logo for simplicity
    'brand_color': '#2563eb'
}

# Generate PDF
invoice = MockInvoice()
pdf_bytes = generate_invoice_pdf(invoice, company_info=company_info)

# Save to file
with open('sample_invoice.pdf', 'wb') as f:
    f.write(pdf_bytes)

print("Sample invoice PDF generated: sample_invoice.pdf")