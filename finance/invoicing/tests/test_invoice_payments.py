from django.test import TestCase
from django.utils import timezone
from decimal import Decimal

from finance.invoicing.models import Invoice, InvoicePayment
from crm.contacts.models import Contact
from business.models import Branch, Bussiness
from finance.accounts.models import PaymentAccounts


class InvoicePaymentRecalcTests(TestCase):
    def setUp(self):
        self.business = Bussiness.objects.create(name='Test Biz')
        self.branch = Branch.objects.create(business=self.business, name='Main')
        self.contact = Contact.objects.create(business_name='Customer', phone='0710000000')

    def test_recalculate_on_invoice_payment_create(self):
        invoice = Invoice.objects.create(
            branch=self.branch,
            customer=self.contact,
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
        )

        # create payment account
        pay_acct = PaymentAccounts.objects.create(name='Main Bank', account_number='123', account_type='bank')

        # create invoice payment should trigger signal and recalc
        ip = InvoicePayment.objects.create(
            invoice=invoice,
            amount=Decimal('40.00'),
            payment_account=pay_acct,
            payment_date=timezone.now().date(),
            notes='test'
        )

        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal('40.00'))
        self.assertEqual(invoice.balance_due, Decimal('60.00'))
        self.assertEqual(invoice.status, 'partially_paid')
