from django.core.management.base import BaseCommand
from django.db import transaction
from finance.accounts.models import PaymentAccounts, AccountTypes
from business.models import Bussiness
from authmanagement.models import CustomUser


class Command(BaseCommand):
    help = 'Seed sample payment accounts for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing payment accounts before seeding',
        )
        parser.add_argument(
            '--count',
            type=int,
            default=5,
            help='Number of payment accounts to create (default: 5)',
        )
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Seed minimal accounts only (defaults to 1 account)',
        )

    def handle(self, *args, **options):
        count = options.get('count', 5)
        minimal = options.get('minimal')
        if minimal:
            count = 1
        
        if options['clear']:
            PaymentAccounts.objects.all().delete()
            self.stdout.write(
                self.style.SUCCESS('Cleared existing payment accounts')
            )

        # Ensure the standard single seeded business exists and use it
        admin_user = CustomUser.objects.filter(is_superuser=True).first()
        if not admin_user:
            admin_user = CustomUser.objects.create_superuser(
                username='admin',
                email='admin@codevertexitsolutions.com',
                password='admin123'
            )
            self.stdout.write(self.style.SUCCESS('Created admin user for demo seeding'))

        business, created = Bussiness.objects.get_or_create(
            name='Codevertex IT Solutions',
            defaults={
                'owner': admin_user,
                'start_date': '2024-01-01',
                'currency': 'KES',
                'kra_number': 'A123456789X',
                'business_type': 'limited_company',
                'county': 'Nairobi'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created business: {business.name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Using existing business: {business.name}'))

        # Remove the created variable reference since we're not using get_or_create anymore

        # First, create account types if they don't exist
        account_types_data = [
            {'name': 'Bank'},
            {'name': 'Cash'},
            {'name': 'Mobile Money'},
            {'name': 'Credit Card'},
            {'name': 'Investment'}
        ]
        
        account_types = {}
        for type_data in account_types_data:
            account_type, created = AccountTypes.objects.get_or_create(
                name=type_data['name']
            )
            account_types[type_data['name'].lower()] = account_type
            if created:
                self.stdout.write(f'Created account type: {account_type.name}')
        
        # Sample payment accounts
        accounts_data = [
            {
                'name': 'Equity Bank - Main Account',
                'account_number': '1234567890',
                'account_type': account_types['bank'],
                'opening_balance': 100000.00
            },
            {
                'name': 'KCB Bank - Savings',
                'account_number': '0987654321',
                'account_type': account_types['bank'],
                'opening_balance': 50000.00
            },
            {
                'name': 'Cooperative Bank - Current',
                'account_number': '1122334455',
                'account_type': account_types['bank'],
                'opening_balance': 75000.00
            },
            {
                'name': 'Cash Register',
                'account_number': 'CASH001',
                'account_type': account_types['cash'],
                'opening_balance': 10000.00
            },
            {
                'name': 'M-Pesa Business',
                'account_number': 'MPESA001',
                'account_type': account_types['mobile money'],
                'opening_balance': 25000.00
            }
        ]

        # Limit accounts to the requested count
        accounts_to_create = accounts_data[:count]

        # Create payment accounts
        created_accounts = []
        with transaction.atomic():
            for account_data in accounts_to_create:
                account, created = PaymentAccounts.objects.get_or_create(
                    name=account_data['name'],
                    defaults=account_data
                )
                
                if created:
                    created_accounts.append(account)
                    self.stdout.write(
                        self.style.SUCCESS(f'Created payment account: {account.name}')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'Payment account already exists: {account.name}')
                    )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {len(created_accounts)} payment accounts')
        )
