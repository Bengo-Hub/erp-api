from django.core.management.base import BaseCommand
from django.db import transaction
from finance.reconciliation.models import BankStatementLine
from finance.accounts.models import PaymentAccounts
from datetime import date, timedelta
import random


class Command(BaseCommand):
    help = 'Seed sample bank statement data for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing bank statement data before seeding',
        )
        parser.add_argument(
            '--count',
            type=int,
            default=50,
            help='Number of bank statement entries to create (default: 50)',
        )
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Seed a minimal set of bank statement entries (default: 1)',
        )

    def handle(self, *args, **options):
        count = options.get('count', 50)
        minimal = options.get('minimal')
        if minimal:
            count = 1
        
        if options['clear']:
            BankStatementLine.objects.all().delete()
            self.stdout.write(
                self.style.SUCCESS('Cleared existing bank statement data')
            )

        # Check if we have payment accounts
        accounts = PaymentAccounts.objects.all()
        if not accounts.exists():
            self.stdout.write(
                self.style.WARNING('No payment accounts found. Please run seed_payment_accounts first.')
            )
            return

        # Sample transaction descriptions
        descriptions = [
            'Salary Payment',
            'Vendor Payment',
            'Customer Refund',
            'Bank Transfer',
            'ATM Withdrawal',
            'Online Purchase',
            'Utility Bill Payment',
            'Insurance Premium',
            'Loan Repayment',
            'Interest Earned',
            'Service Charge',
            'Deposit',
            'Withdrawal',
            'Payment Received',
            'Commission Payment'
        ]

        # Generate sample data
        sample_data = []
        start_date = date.today() - timedelta(days=30)
        
        for i in range(count):  # Create the requested number of entries
            account = random.choice(accounts)
            statement_date = start_date + timedelta(days=random.randint(0, 30))
            amount = random.uniform(-10000, 15000)  # Mix of positive and negative amounts
            description = random.choice(descriptions)
            
            sample_data.append(BankStatementLine(
                account=account,
                statement_date=statement_date,
                description=description,
                amount=round(amount, 2),
                external_ref=f'REF-{random.randint(1000, 9999)}',
                is_reconciled=random.choice([True, False])
            ))

        # Bulk create the data
        with transaction.atomic():
            BankStatementLine.objects.bulk_create(sample_data)

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {len(sample_data)} bank statement entries')
        )
