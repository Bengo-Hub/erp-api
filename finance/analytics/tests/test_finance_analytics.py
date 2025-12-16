from django.test import TestCase
from django.utils import timezone
from decimal import Decimal

from finance.analytics.finance_analytics import FinanceAnalyticsService
from finance.invoicing.models import Invoice
from finance.invoicing.models import InvoicePayment
from finance.payment.models import Payment
from business.models import Bussiness, Branch
from crm.contacts.models import Contact


class FinanceAnalyticsTests(TestCase):
    def setUp(self):
        self.biz = Bussiness.objects.create(name='TestBiz')
        self.branch = Branch.objects.create(business=self.biz, name='Main')
        self.contact = Contact.objects.create(business_name='Customer')

    def test_financial_summary_includes_invoices(self):
        # create an invoice and a payment
        invoice = Invoice.objects.create(
            branch=self.branch,
            customer=self.contact,
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00')
        )

        # create payment linked to invoice
        payment = Payment.objects.create(
            payment_type='invoice_payment',
            amount=Decimal('100.00'),
            payment_method='bank',
            reference_number='PAYTEST',
            payment_date=timezone.now(),
            customer=self.contact,
            status='completed'
        )

        InvoicePayment.objects.create(invoice=invoice, payment=payment, amount=Decimal('100.00'), payment_account_id=1, payment_date=timezone.now().date())

        service = FinanceAnalyticsService()
        start_date = timezone.now().date() - timezone.timedelta(days=1)
        end_date = timezone.now().date() + timezone.timedelta(days=1)

        summary = service.get_financial_summary(start_date, end_date, business_id=None)
        self.assertGreaterEqual(summary['total_invoices'], 100)
        self.assertGreaterEqual(summary['total_payments'], 100)