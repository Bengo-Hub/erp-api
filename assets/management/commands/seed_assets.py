from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from decimal import Decimal
from faker import Faker
import random

# Import models
from assets.models import (
    AssetCategory, Asset, AssetTransfer, AssetMaintenance,
    AssetDisposal, AssetInsurance, AssetAudit, AssetReservation
)
from business.models import Branch, Bussiness, BusinessLocation

# Get the custom user model
User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds sample asset management data for testing and demonstration'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake = Faker()  # Use default locale for realistic data
        Faker.seed(42)  # Consistent seed for reproducible data

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete existing data before seeding',
        )
        parser.add_argument(
            '--users',
            type=int,
            default=1,
            help='Number of users to create (default: 1)',
        )
        parser.add_argument(
            '--categories',
            type=int,
            default=2,
            help='Number of asset categories to create (default: 2)',
        )
        parser.add_argument(
            '--assets',
            type=int,
            default=2,
            help='Number of assets to create (default: 2)',
        )
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Seed minimal asset data (1 user, 1 category, 1 asset)',
        )

    def handle(self, *args, **options):
        clear = options['clear']
        num_users = options['users']
        num_categories = options['categories']
        num_assets = options['assets']
        minimal = options.get('minimal')
        if minimal:
            num_users = 1
            num_categories = 1
            num_assets = 1

        if clear:
            self.stdout.write(
                self.style.WARNING('Resetting existing asset data...')
            )
            self.reset_data()

        self.stdout.write(
            self.style.SUCCESS(f'Seeding {num_categories} categories, {num_assets} assets, and related data...')
        )

        with transaction.atomic():
            # Create sample users
            users = self.create_sample_users(num_users)

            # Create sample branches
            branches = self.create_sample_branches()

            # Create asset categories
            categories = self.create_asset_categories(num_categories)

            # Create assets
            assets = self.create_assets(num_assets, categories, branches, users)

            # Create asset transfers
            self.create_asset_transfers(assets, users, branches)

            # Create asset maintenance records
            self.create_asset_maintenance(assets, users)

            # Create asset disposals
            self.create_asset_disposals(assets, users)

            # Create asset insurance records
            self.create_asset_insurance(assets, users)

            # Create asset audits
            self.create_asset_audits(assets, users)

            # Create asset reservations
            self.create_asset_reservations(assets, users)

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully seeded asset management data:\n'
                f'  • {len(categories)} asset categories\n'
                f'  • {len(assets)} assets\n'
                f'  • {AssetTransfer.objects.count()} transfers\n'
                f'  • {AssetMaintenance.objects.count()} maintenance records\n'
                f'  • {AssetDisposal.objects.count()} disposals\n'
                f'  • {AssetInsurance.objects.count()} insurance records\n'
                f'  • {AssetAudit.objects.count()} audits\n'
                f'  • {AssetReservation.objects.count()} reservations'
            )
        )

    def reset_data(self):
        """Delete existing asset data"""
        models_to_clear = [
            AssetReservation,
            AssetAudit,
            AssetInsurance,
            AssetDisposal,
            AssetMaintenance,
            AssetTransfer,
            Asset,
            AssetCategory,
        ]

        for model in models_to_clear:
            model.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS('Existing asset data cleared')
        )

    def create_sample_users(self, num_users):
        """Create sample users"""
        users = []
        base_names = [
            ('John', 'Doe'), ('Jane', 'Smith'), ('Michael', 'Johnson'),
            ('Sarah', 'Williams'), ('David', 'Brown'), ('Lisa', 'Davis'),
            ('Robert', 'Miller'), ('Jennifer', 'Wilson'), ('James', 'Moore'),
            ('Maria', 'Taylor')
        ]

        for i in range(num_users):
            first_name, last_name = base_names[i % len(base_names)]
            username = f'{first_name.lower()}.{last_name.lower()}{i+1}'
            email = f'{username}@codevertexitsolutions.com'

            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'is_staff': random.choice([True, False]),
                    'is_active': True,
                }
            )

            if created:
                user.set_password('password123')
                user.save()

            users.append(user)

        return users

    def create_sample_branches(self):
        """Create sample branches"""
        # Find or create the canonical business
        business, created = Bussiness.objects.get_or_create(
            name='Codevertex IT Solutions',
            defaults={
                'owner': self.get_or_create_demo_user(),
                'start_date': timezone.now().date(),
                'currency': 'KES',
                'business_type': 'limited_company',
            }
        )

        # Ensure the business has a location
        location = business.location if business.location and business.location.default and business.location.is_active else None
        if not location:
            location = BusinessLocation.objects.create(
                city='Nairobi',
                county='Nairobi',
                country='KE',
                default=True,
                is_active=True
            )
            business.location = location
            business.save()

        # Ensure a single HQ branch exists and return it
        main_branch = Branch.objects.filter(business=business, is_main_branch=True).first()
        if not main_branch:
            main_branch, _ = Branch.objects.get_or_create(
                branch_code='HQ-001',
                defaults={
                    'business': business,
                    'location': location,
                    'name': 'HQ',
                    'contact_number': '+254700000000',
                    'email': 'info@codevertexitsolutions.com',
                    'is_active': True,
                    'is_main_branch': True
                }
            )

        return [main_branch]

    def get_or_create_demo_user(self):
        """Get or create a demo user"""
        user, created = User.objects.get_or_create(
            username='demo',
            defaults={
                'first_name': 'Demo',
                'last_name': 'User',
                'email': 'demo@codevertexitsolutions.com',
                'is_staff': True,
                'is_active': True,
            }
        )
        if created:
            user.set_password('demo123')
            user.save()
        return user

    def create_asset_categories(self, num_categories):
        """Create asset categories"""
        categories_data = [
            {
                'name': 'Computers & Laptops',
                'description': 'Desktop computers, laptops, and related accessories',
                'depreciation_rate': Decimal('25.00'),
                'useful_life_years': 4
            },
            {
                'name': 'Office Furniture',
                'description': 'Desks, chairs, cabinets, and office furniture',
                'depreciation_rate': Decimal('10.00'),
                'useful_life_years': 10
            },
        ]

        categories = []
        for i, category_data in enumerate(categories_data[:num_categories]):
            category, created = AssetCategory.objects.get_or_create(
                name=category_data['name'],
                defaults={
                    'description': category_data['description'],
                    'depreciation_rate': category_data['depreciation_rate'],
                    'useful_life_years': category_data['useful_life_years'],
                    'is_active': True,
                }
            )
            categories.append(category)

        return categories

    def create_assets(self, num_assets, categories, branches, users):
        """Create sample assets"""
        assets = []
        asset_types = [
            'Laptop', 'Desktop', 'Chair', 'Desk', 'Vehicle', 'Printer',
            'Phone', 'Tablet', 'Server', 'Router', 'Projector', 'Camera'
        ]

        manufacturers = [
            'Dell', 'HP', 'Lenovo', 'Apple', 'Samsung', 'Sony',
            'Canon', 'Epson', 'Brother', 'Cisco', 'Huawei', 'Microsoft'
        ]

        for i in range(num_assets):
            category = random.choice(categories)
            branch = random.choice(branches)
            assigned_user = random.choice(users) if random.choice([True, False]) else None
            custodian = random.choice(users) if random.choice([True, True]) else None

            # Generate realistic asset data
            asset_type = random.choice(asset_types)
            manufacturer = random.choice(manufacturers)

            purchase_cost = Decimal(str(round(random.uniform(5000, 500000), 2)))
            purchase_date = self.fake.date_between(start_date='-3y', end_date='-1d')

            # Calculate current value (with some depreciation)
            age_years = (timezone.now().date() - purchase_date).days / 365
            depreciation_rate_float = float(category.depreciation_rate) / 100
            depreciation_amount = age_years * depreciation_rate_float
            current_value = float(purchase_cost) * (1 - depreciation_amount)

            asset = Asset.objects.create(
                asset_tag=f'AST-{timezone.now().strftime("%Y%m%d%H%M%S")}-{i+1:04d}',
                name=f'{manufacturer} {asset_type} {i+1}',
                description=f'Sample {asset_type.lower()} for {category.name.lower()}',
                category=category,
                serial_number=f'SN{random.randint(100000, 999999)}',
                model=f'{asset_type}-{random.randint(100, 999)}',
                purchase_date=purchase_date,
                purchase_cost=purchase_cost,
                current_value=max(Decimal(str(current_value)), purchase_cost * Decimal('0.1')),  # Minimum 10% of original value
                salvage_value=purchase_cost * Decimal('0.05'),  # 5% salvage value
                depreciation_rate=category.depreciation_rate,
                location=self.fake.address()[:100],
                branch=branch,
                assigned_to=assigned_user,
                custodian=custodian,
                status=random.choice(['active', 'active', 'active', 'inactive', 'maintenance']),
                condition=random.choice(['excellent', 'good', 'good', 'fair']),
                warranty_expiry=purchase_date.replace(year=purchase_date.year + random.randint(1, 3)),
                is_active=True,
                created_by=random.choice(users)
            )
            assets.append(asset)

        return assets

    def create_asset_transfers(self, assets, users, branches):
        """Create sample asset transfers"""
        num_transfers = min(len(assets) // 3, 2)  # Create transfers for about 1/3 of assets

        for i in range(num_transfers):
            asset = random.choice(assets)
            from_user = random.choice(users)
            to_user = random.choice(users)
            from_branch = random.choice(branches)
            to_branch = random.choice(branches)

            transfer_date = self.fake.date_time_between(start_date='-1y', end_date='-1d')

            AssetTransfer.objects.create(
                asset=asset,
                from_location=f'{from_branch.name} - {self.fake.address()[:50]}',
                to_location=f'{to_branch.name} - {self.fake.address()[:50]}',
                from_user=from_user,
                to_user=to_user,
                transfer_date=transfer_date,
                status=random.choice(['completed', 'completed', 'completed', 'in_transit', 'pending']),
                reason=random.choice([
                    'Department Transfer',
                    'Employee Assignment',
                    'Location Change',
                    'Maintenance Transfer'
                ]),
                transferred_by=from_user,
                notes=f'Sample transfer {i+1}',
                tracking_number=f'TR{random.randint(1000, 9999)}'
            )

    def create_asset_maintenance(self, assets, users):
        """Create sample asset maintenance records"""
        num_maintenance = min(len(assets) // 2, 1)

        for i in range(num_maintenance):
            asset = random.choice(assets)
            maintenance_date = self.fake.date_time_between(start_date='-6M', end_date='-1d')

            AssetMaintenance.objects.create(
                asset=asset,
                maintenance_type=random.choice(['preventive', 'corrective', 'preventive']),
                scheduled_date=maintenance_date.date(),
                completed_date=maintenance_date.date() if random.choice([True, False]) else None,
                performed_by=self.fake.name(),
                cost=Decimal(str(round(random.uniform(1000, 50000), 2))),
                description=f'Sample maintenance for {asset.name}',
                status=random.choice(['completed', 'completed', 'scheduled', 'in_progress']),
                priority=random.choice(['low', 'medium', 'high']),
                downtime_hours=Decimal(str(random.randint(1, 48)))
            )

    def create_asset_disposals(self, assets, users):
        """Create sample asset disposals"""
        num_disposals = min(len(assets) // 5, 1)  # Dispose of about 20% of assets

        for i in range(num_disposals):
            asset = random.choice(assets)
            disposal_date = self.fake.date_between(start_date='-1y', end_date='-1d')

            AssetDisposal.objects.create(
                asset=asset,
                disposal_date=disposal_date,
                disposal_method=random.choice(['sold', 'scrapped', 'donated']),
                disposal_value=asset.current_value * Decimal(str(random.uniform(0.1, 0.8))),
                reason='Sample disposal reason',
                approved_by=random.choice(users),
                status=random.choice(['completed', 'approved', 'pending']),
                notes=f'Sample disposal {i+1}'
            )

    def create_asset_insurance(self, assets, users):
        """Create sample asset insurance records"""
        num_insurance = min(len(assets) // 3, 1)

        for i in range(num_insurance):
            asset = random.choice(assets)
            start_date = self.fake.date_between(start_date='-2y', end_date='-6M')
            end_date = self.fake.date_between(start_date=start_date, end_date='+1y')

            AssetInsurance.objects.create(
                asset=asset,
                policy_number=f'POL{random.randint(10000, 99999)}',
                provider=random.choice(['Jubilee Insurance', 'CIC Insurance', 'Britam', 'UAP']),
                policy_type='Comprehensive Coverage',
                coverage_amount=asset.purchase_cost * Decimal('1.1'),
                premium_amount=asset.purchase_cost * Decimal('0.02'),
                start_date=start_date,
                end_date=end_date,
                deductible=Decimal(str(random.randint(5000, 25000))),
                is_active=end_date > timezone.now().date(),
                notes=f'Sample insurance policy {i+1}'
            )

    def create_asset_audits(self, assets, users):
        """Create sample asset audits"""
        num_audits = min(len(assets) // 4, 1)

        for i in range(num_audits):
            asset = random.choice(assets)
            audit_date = self.fake.date_between(start_date='-1y', end_date='-1d')

            AssetAudit.objects.create(
                asset=asset,
                audit_date=audit_date,
                auditor=random.choice(users),
                status=random.choice(['completed', 'completed', 'in_progress']),
                location_verified=self.fake.address()[:100],
                condition_verified=random.choice(['excellent', 'good', 'fair']),
                custodian_verified=random.choice(users),
                next_audit_date=audit_date.replace(year=audit_date.year + 1)
            )

    def create_asset_reservations(self, assets, users):
        """Create sample asset reservations"""
        num_reservations = min(len(assets) // 4, 1)

        for i in range(num_reservations):
            asset = random.choice(assets)
            reserved_by = random.choice(users)

            # Generate future dates for reservations
            start_date = self.fake.date_time_between(start_date='+1d', end_date='+30d')
            end_date = self.fake.date_time_between(start_date=start_date, end_date='+60d')

            AssetReservation.objects.create(
                asset=asset,
                reserved_by=reserved_by,
                start_date=start_date,
                end_date=end_date,
                purpose=f'Sample reservation for {asset.name}',
                status=random.choice(['approved', 'pending', 'active']),
                approved_by=random.choice(users) if random.choice([True, False]) else None,
                notes=f'Sample reservation {i+1}'
            )
