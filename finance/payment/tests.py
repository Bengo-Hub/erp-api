from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from business.models import Bussiness, Branch, BusinessLocation
from crm.contacts.models import Contact
from django.contrib.auth import get_user_model
from finance.payment.models import Payment
from finance.accounts.models import PaymentAccounts, Transaction


class PaymentTransactionTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(username='paytest', email='paytest@example.com', password='testpass')
        self.client.force_authenticate(user=self.user)

        # Create business and branch
        loc = BusinessLocation.objects.create(city='Nairobi')
        self.business = Bussiness.objects.create(owner=self.user, name='PayCo', location=loc)
        self.branch = Branch.objects.create(business=self.business, location=loc, name='Main', branch_code='MB100')

        # Payment account
        self.account = PaymentAccounts.objects.create(name='Bank A', account_number='123456', account_type='bank', opening_balance=0)

    def test_transaction_created_on_completed_payment(self):
        payment = Payment.objects.create(
            payment_type='invoice_payment',
            direction='in',
            amount=1000,
            payment_method='bank',
            status='completed',
            reference_number='TEST-PAY-1',
            payment_account=self.account,
            payment_date=timezone.now()
        )

        # A Transaction should be created for the payment account
        tx = Transaction.objects.filter(reference_type='payment', reference_id=str(payment.reference_number)).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, payment.amount)
        self.assertEqual(tx.account.id, self.account.id)

    def test_account_balance_reflects_transactions(self):
        # Create two payments
        Payment.objects.create(payment_type='invoice_payment', direction='in', amount=1500, payment_method='bank', status='completed', reference_number='PAY-1', payment_account=self.account, payment_date=timezone.now())
        Payment.objects.create(payment_type='invoice_payment', direction='in', amount=500, payment_method='bank', status='completed', reference_number='PAY-2', payment_account=self.account, payment_date=timezone.now())

        # Reload account and compute balance via serializer helper in accounts
        from finance.accounts.serializers import PaymentAccountsSerializer
        serializer = PaymentAccountsSerializer(self.account)
        balance = serializer.data.get('balance')
        # opening_balance was 0, two incoming payments -> balance should be 2000
        self.assertEqual(str(balance), '2000.00')
