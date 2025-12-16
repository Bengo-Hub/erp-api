from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from business.models import Bussiness, Branch, BusinessLocation
from crm.contacts.models import Contact
from ecommerce.product.models import Products
from django.contrib.auth import get_user_model


class InvoicePDFRefreshTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(username='invtest', email='invtest@example.com', password='testpass')
        self.client.force_authenticate(user=self.user)

        # Create business and branch
        loc = BusinessLocation.objects.create(city='Nairobi')
        self.business = Bussiness.objects.create(owner=self.user, name='InvCo', location=loc)
        self.branch = Branch.objects.create(business=self.business, location=loc, name='Main', branch_code='MB200')

        # Customer and product
        self.contact = Contact.objects.create(contact_id='CUST-INV', user=self.user, designation='Mr', created_by=self.user, business=self.business)
        self.product = Products.objects.create(title='Invoice Item', business=self.business, product_type='service', default_price=2500)

    def test_invoice_pdf_etag_updates_when_items_change(self):
        # Create invoice
        url = '/api/v1/finance/invoicing/invoices/'
        payload = {
            'customer': self.contact.id,
            'branch': self.branch.id,
            'invoice_date': timezone.now().date().isoformat(),
            'due_date': (timezone.now().date()).isoformat(),
            'subtotal': 2500,
            'tax_amount': 400,
            'total': 2900,
            'items': [
                {
                    'description': 'Service A',
                    'quantity': 1,
                    'unit_price': 2500,
                    'subtotal': 2500,
                    'total': 2900,
                    'product_id': self.product.id
                }
            ]
        }

        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json().get('data')
        invoice_id = data['id']

        pdf_url = f"/api/v1/finance/invoicing/invoices/{invoice_id}/pdf/"
        first = self.client.get(pdf_url)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertIn('ETag', first)
        old_etag = first['ETag']

        # Modify an item directly
        from core_orders.models import OrderItem
        item = OrderItem.objects.filter(order__id=invoice_id).first()
        item.unit_price = item.unit_price + 100
        item.save()

        # Fetch with old ETag - should get new content and a new ETag
        after = self.client.get(pdf_url, **{'HTTP_IF_NONE_MATCH': old_etag})
        self.assertEqual(after.status_code, status.HTTP_200_OK)
        self.assertIn('ETag', after)
        self.assertNotEqual(after['ETag'], old_etag)

        # Subsequent request with latest ETag should return 304
        fresh = self.client.get(pdf_url, **{'HTTP_IF_NONE_MATCH': after['ETag']})
        self.assertEqual(fresh.status_code, status.HTTP_304_NOT_MODIFIED)

    def test_record_payment_creates_account_transaction(self):
        # Create invoice
        url = '/api/v1/finance/invoicing/invoices/'
        payload = {
            'customer': self.contact.id,
            'branch': self.branch.id,
            'invoice_date': timezone.now().date().isoformat(),
            'due_date': (timezone.now().date()).isoformat(),
            'subtotal': 2500,
            'tax_amount': 400,
            'total': 2900,
            'items': [
                {
                    'description': 'Service A',
                    'quantity': 1,
                    'unit_price': 2500,
                    'subtotal': 2500,
                    'total': 2900,
                    'product_id': self.product.id
                }
            ]
        }

        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json().get('data')
        invoice_id = data['id']

        # Create payment account
        from finance.accounts.models import PaymentAccounts, Transaction
        account = PaymentAccounts.objects.create(name='Bank B', account_number='ACC-4321', account_type='bank', opening_balance=0)

        record_url = f"/api/v1/finance/invoicing/invoices/{invoice_id}/record-payment/"
        pay_payload = {
            'amount': '2900.00',
            'payment_method': 'bank',
            'payment_account': account.id,
            'reference': 'API-PAY-1'
        }

        pay_resp = self.client.post(record_url, pay_payload, format='json')
        self.assertEqual(pay_resp.status_code, status.HTTP_200_OK)

        # Ensure a Transaction was created for the payment_account
        tx = Transaction.objects.filter(reference_type='payment', reference_id__icontains='API-PAY-1').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.account.id, account.id)

    def test_invoice_payment_link_updates_payment_and_creates_transaction(self):
        # Create invoice
        url = '/api/v1/finance/invoicing/invoices/'
        payload = {
            'customer': self.contact.id,
            'branch': self.branch.id,
            'invoice_date': timezone.now().date().isoformat(),
            'due_date': (timezone.now().date()).isoformat(),
            'subtotal': 2500,
            'tax_amount': 400,
            'total': 2900,
            'items': [
                {
                    'description': 'Service A',
                    'quantity': 1,
                    'unit_price': 2500,
                    'subtotal': 2500,
                    'total': 2900,
                    'product_id': self.product.id
                }
            ]
        }

        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json().get('data')
        invoice_id = data['id']

        # Create payment without account
        from finance.payment.models import Payment
        payment = Payment.objects.create(payment_type='invoice_payment', direction='in', amount=1000, payment_method='bank', status='completed', reference_number='LINK-PAY-1', payment_date=timezone.now(), customer=self.contact)

        # Create payment account and then create InvoicePayment linking the payment to the account
        from finance.accounts.models import PaymentAccounts, Transaction
        account = PaymentAccounts.objects.create(name='Bank C', account_number='ACC-999', account_type='bank', opening_balance=0)

        inv_payment = {
            'invoice': invoice_id,
            'payment': payment.id,
            'amount': '1000.00',
            'payment_account': account.id,
            'payment_date': timezone.now().date().isoformat(),
            'notes': 'Linked payment'
        }

        ip_url = '/api/v1/finance/invoicing/invoice-payments/'
        ip_resp = self.client.post(ip_url, inv_payment, format='json')
        self.assertIn(ip_resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

        # After creating InvoicePayment, the underlying Payment should have been updated with account
        payment.refresh_from_db()
        self.assertIsNotNone(payment.payment_account)
        self.assertEqual(payment.payment_account.id, account.id)

        # And a Transaction should exist for this payment
        tx = Transaction.objects.filter(reference_type='payment', reference_id__icontains='LINK-PAY-1').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.account.id, account.id)

    def test_invoice_pdf_includes_company_address_from_hq_branch(self):
        # Create a business with a main HQ branch (no branch on invoice)
        loc = BusinessLocation.objects.create(building_name='Suite 200', street_name='Mwembe Lane', city='Nairobi', county='Nairobi', state='Nairobi State', country='Kenya')
        biz = Bussiness.objects.create(owner=self.user, name='KuraWeigh Solutions Ltd', location=loc, email='procurement@kuraweigh.com')
        main = Branch.objects.create(business=biz, location=loc, name='HQ', branch_code='HQ-1', is_main_branch=True, is_active=True, contact_number='+254 701 987 654')

        # Create customer and product
        contact = Contact.objects.create(contact_id='CUST-PDF', user=self.user, designation='Mr', created_by=self.user, business=biz)
        product = Products.objects.create(title='PDF Test', business=biz, product_type='service', default_price=1234)

        # Create invoice without specifying branch (should pick up HQ branch info)
        url = '/api/v1/finance/invoicing/invoices/'
        payload = {
            'customer': contact.id,
            'invoice_date': timezone.now().date().isoformat(),
            'due_date': (timezone.now().date()).isoformat(),
            'subtotal': 1234,
            'tax_amount': 0,
            'total': 1234,
            'items': [
                {
                    'description': 'Service HQ',
                    'quantity': 1,
                    'unit_price': 1234,
                    'subtotal': 1234,
                    'total': 1234,
                    'product_id': product.id
                }
            ]
        }

        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json().get('data')
        invoice_id = data['id']

        pdf_url = f"/api/v1/finance/invoicing/invoices/{invoice_id}/pdf/"
        pdf_resp = self.client.get(pdf_url)
        self.assertEqual(pdf_resp.status_code, status.HTTP_200_OK)
        pdf_bytes = pdf_resp.content

        # Check that company name, address components, email and phone are present in the generated PDF bytes
        self.assertIn(b'KuraWeigh Solutions Ltd', pdf_bytes)
        self.assertIn(b'Mwembe Lane', pdf_bytes)
        self.assertIn(b'Nairobi', pdf_bytes)
        self.assertIn(b'Kenya', pdf_bytes)
        self.assertIn(b'procurement@kuraweigh.com', pdf_bytes)
        self.assertIn(b'+254 701 987 654', pdf_bytes)
from django.test import TestCase

# Tests are intentionally omitted. Please request specific tests if needed.
