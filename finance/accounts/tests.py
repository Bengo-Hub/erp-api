from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from business.models import Bussiness, BusinessLocation, Branch
from finance.accounts.models import PaymentAccounts, Transaction
from django.utils import timezone


class PaymentAccountsAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(username='accttest', email='accttest@example.com', password='testpass')
        self.client.force_authenticate(user=self.user)

        loc = BusinessLocation.objects.create(city='Nairobi')
        self.business = Bussiness.objects.create(owner=self.user, name='AcctCo', location=loc)
        self.branch = Branch.objects.create(business=self.business, location=loc, name='Main', branch_code='MBX')

    def test_create_account_with_display_account_type(self):
        url = '/api/v1/finance/accounts/paymentaccounts/'
        payload = {
            'name': 'Equity Bank - Main Account',
            'account_number': '1234567890',
            'account_type': 'Bank',
            'currency': 'KES',
            'opening_balance': 0,
            'status': 'active'
        }

        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json().get('data') or resp.json()
        self.assertEqual(data.get('account_type'), 'bank')
        # Ensure display label is returned
        self.assertIn('account_type_display', data)
        self.assertTrue(data.get('account_type_display'))

    def test_create_cash_account_without_account_number(self):
        url = '/api/v1/finance/accounts/paymentaccounts/'
        payload = {
            'name': 'Cash Till',
            'account_type': 'Cash',
            'currency': 'KES',
            'opening_balance': 5000,
            'status': 'active'
        }

        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json().get('data') or resp.json()
        # account_type should be normalized to 'cash'
        self.assertEqual(data.get('account_type'), 'cash')
        # account_number should have been generated
        self.assertIn('account_number', data)
        self.assertTrue(data.get('account_number'))

    def test_transactions_filtering_and_ordering(self):
        # Create account
        acct = PaymentAccounts.objects.create(name='Test', account_number='ACC100', account_type='bank')

        # Create transactions
        t1 = Transaction.objects.create(account=acct, transaction_date=timezone.now(), amount=100, transaction_type='income', description='Inc 1', reference_type='payment', reference_id='R1', created_by=None)
        t2 = Transaction.objects.create(account=acct, transaction_date=timezone.now(), amount=50, transaction_type='payment', description='Pay 1', reference_type='payment', reference_id='R2', created_by=None)
        t3 = Transaction.objects.create(account=acct, transaction_date=timezone.now(), amount=200, transaction_type='income', description='Inc 2', reference_type='payment', reference_id='R3', created_by=None)

        base = f'/api/v1/finance/accounts/paymentaccounts/{acct.id}/transactions/'

        # Filter by transaction_type=income
        resp = self.client.get(base, {'transaction_type': 'income'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()
        results = body.get('results') or body.get('data') or body
        self.assertTrue(all(r['transaction_type'] == 'income' for r in results))

        # Ordering by amount asc
        resp2 = self.client.get(base, {'ordering': 'amount'})
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        body2 = resp2.json()
        results2 = body2.get('results') or body2.get('data') or body2
        amounts = [float(r['amount']) for r in results2]
        self.assertEqual(amounts, sorted(amounts))
from django.test import TestCase

# Create your tests here.
