from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from crm.contacts.models import Contact, CustomerGroup
from business.models import Bussiness, Branch
from decimal import Decimal
import random

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds CRM contacts (Customers and Suppliers) for each business'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=5,
            help='Number of customers and suppliers to create per business (default: 1 each)',
        )
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Seed minimal contacts per business (1 supplier, 1 customer)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing contacts before seeding',
        )

    def handle(self, *args, **options):
        count = options['count']
        minimal = options.get('minimal')
        if minimal:
            count = 1
        
        if options['clear']:
            self.stdout.write('Clearing existing contacts...')
            Contact.objects.all().delete()
            CustomerGroup.objects.all().delete()

        self.stdout.write(self.style.SUCCESS(f'Starting to seed CRM contacts ({count} customers and {count} suppliers per business)...'))

        # Get all businesses
        businesses = Bussiness.objects.all()
        if not businesses.exists():
            self.stdout.write(self.style.ERROR('No businesses found. Please run seed_business_data first.'))
            return

        # Get admin user as creator
        admin_user = User.objects.filter(username='admin').first()
        if not admin_user:
            admin_user = User.objects.filter(is_superuser=True).first()
        
        if not admin_user:
            self.stdout.write(self.style.ERROR('No admin user found. Please create an admin user first.'))
            return

        # Create customer groups
        customer_groups = self._create_customer_groups()

        total_contacts = 0
        
        for business in businesses:
            self.stdout.write(f'\nSeeding contacts for business: {business.name}')
            
            # Get first branch of this business
            branch = business.branches.first()
            if not branch:
                self.stdout.write(self.style.WARNING(f'  No branch found for {business.name}, skipping...'))
                continue

            # Create default supplier (critical for testing procurement)
            default_supplier = self._create_default_supplier(business, branch, admin_user)
            total_contacts += 1
            self.stdout.write(self.style.SUCCESS(f'  ✓ Created default supplier: {default_supplier.business_name}'))

            # Create default customer (critical for testing invoices, quotes)
            default_customer = self._create_default_customer(business, branch, admin_user, customer_groups)
            total_contacts += 1
            self.stdout.write(self.style.SUCCESS(f'  ✓ Created default customer: {default_customer.user.get_full_name()}'))

            # Create additional suppliers
            for i in range(count - 1):  # -1 because we already created default
                supplier = self._create_supplier(business, branch, admin_user, i + 2)
                total_contacts += 1

            # Create additional customers
            for i in range(count - 1):  # -1 because we already created default
                customer = self._create_customer(business, branch, admin_user, customer_groups, i + 2)
                total_contacts += 1

            self.stdout.write(self.style.SUCCESS(f'  ✓ Created {count} suppliers and {count} customers for {business.name}'))

        self.stdout.write(
            self.style.SUCCESS(
                f'\n✓ Contact seeding completed!\n'
                f'  - Total contacts created: {total_contacts}\n'
                f'  - Customer groups: {len(customer_groups)}\n'
                f'  - Each business has at least 1 default supplier and 1 default customer'
            )
        )

    def _create_customer_groups(self):
        """Create customer groups for discounts."""
        groups_data = [
            {'group_name': 'Retail', 'dicount_calculation': 'Percentage', 'amount': Decimal('5.00')},
            {'group_name': 'Wholesale', 'dicount_calculation': 'Percentage', 'amount': Decimal('15.00')},
            {'group_name': 'VIP', 'dicount_calculation': 'Percentage', 'amount': Decimal('20.00')},
        ]
        
        groups = []
        for data in groups_data:
            group, created = CustomerGroup.objects.get_or_create(
                group_name=data['group_name'],
                defaults=data
            )
            groups.append(group)
        
        return groups

    def _create_default_supplier(self, business, branch, admin_user):
        """Create a default supplier for testing procurement workflows."""
        # Create or get user for supplier
        supplier_email = f'supplier.default@{business.name.lower().replace(" ", "")}.com'
        supplier_user, created = User.objects.get_or_create(
            email=supplier_email,
            defaults={
                'username': f'supplier_default_{business.id}',
                'first_name': 'Default',
                'last_name': 'Supplier',
                'is_active': True,
            }
        )
        if created:
            supplier_user.set_password('Supplier@2025!')
            supplier_user.save()

        # Create supplier contact
        contact, created = Contact.objects.get_or_create(
            user=supplier_user,
            business=business,
            contact_type='Suppliers',
            defaults={
                'contact_id': f'SUP-DEFAULT-{business.id}',
                'branch': branch,
                'designation': 'Mr',
                'account_type': 'Business',
                'business_name': f'{business.name} Default Supplier Ltd',
                'business_address': 'P.O. Box 12345-00100, Nairobi',
                'tax_number': 'P051234567A',
                'phone': '+254712345678',
                'alternative_contact': '+254722345678',
                'credit_limit': Decimal('1000000.00'),
                'created_by': admin_user,
            }
        )
        
        return contact

    def _create_default_customer(self, business, branch, admin_user, customer_groups):
        """Create a default customer for testing invoices and quotes."""
        # Create or get user for customer
        customer_email = f'customer.default@{business.name.lower().replace(" ", "")}.com'
        customer_user, created = User.objects.get_or_create(
            email=customer_email,
            defaults={
                'username': f'customer_default_{business.id}',
                'first_name': 'John',
                'last_name': 'Doe',
                'is_active': True,
            }
        )
        if created:
            customer_user.set_password('Customer@2025!')
            customer_user.save()

        # Create customer contact
        contact, created = Contact.objects.get_or_create(
            user=customer_user,
            business=business,
            contact_type='Customers',
            defaults={
                'contact_id': f'CUST-DEFAULT-{business.id}',
                'branch': branch,
                'designation': 'Mr',
                'customer_group': random.choice(customer_groups),
                'account_type': 'Individual',
                'phone': '+254711111111',
                'alternative_contact': '+254722222222',
                'credit_limit': Decimal('50000.00'),
                'created_by': admin_user,
            }
        )
        
        return contact

    def _create_supplier(self, business, branch, admin_user, index):
        """Create a supplier contact."""
        supplier_names = [
            'ABC Supplies Ltd', 'Global Traders Inc', 'Prime Vendors Co',
            'Elite Distributors', 'Quality Goods Ltd', 'Top Suppliers Inc',
            'Premium Products Ltd', 'Best Wholesale Co', 'Super Supplies Ltd'
        ]
        
        supplier_email = f'supplier{index}@{business.name.lower().replace(" ", "")}.com'
        supplier_user, created = User.objects.get_or_create(
            email=supplier_email,
            defaults={
                'username': f'supplier{index}_{business.id}',
                'first_name': f'Supplier{index}',
                'last_name': 'Business',
                'is_active': True,
            }
        )
        if created:
            supplier_user.set_password('Supplier@2025!')
            supplier_user.save()

        contact = Contact.objects.create(
            contact_id=f'SUP-{business.id:04d}-{index:04d}',
            contact_type='Suppliers',
            user=supplier_user,
            business=business,
            branch=branch,
            designation='Mr',
            account_type='Business',
            business_name=supplier_names[index % len(supplier_names)],
            business_address=f'P.O. Box {10000 + index * 100}-00100, Nairobi',
            tax_number=f'P05{100000 + index:06d}A',
            phone=f'+2547{70000000 + index:08d}',
            alternative_contact=f'+2547{80000000 + index:08d}',
            credit_limit=Decimal(random.randint(100000, 5000000)),
            created_by=admin_user,
        )
        
        return contact

    def _create_customer(self, business, branch, admin_user, customer_groups, index):
        """Create a customer contact."""
        first_names = ['James', 'Mary', 'Peter', 'Jane', 'David', 'Sarah', 'Michael', 'Grace', 'Joseph', 'Ruth']
        last_names = ['Kamau', 'Wanjiru', 'Ochieng', 'Akinyi', 'Mwangi', 'Njeri', 'Otieno', 'Wambui', 'Kiprop', 'Chebet']
        
        customer_email = f'customer{index}@{business.name.lower().replace(" ", "")}.com'
        customer_user, created = User.objects.get_or_create(
            email=customer_email,
            defaults={
                'username': f'customer{index}_{business.id}',
                'first_name': first_names[index % len(first_names)],
                'last_name': last_names[index % len(last_names)],
                'is_active': True,
            }
        )
        if created:
            customer_user.set_password('Customer@2025!')
            customer_user.save()

        contact = Contact.objects.create(
            contact_id=f'CUST-{business.id:04d}-{index:04d}',
            contact_type='Customers',
            user=customer_user,
            business=business,
            branch=branch,
            designation=random.choice(['Mr', 'Mrs', 'Ms', 'Dr']),
            customer_group=random.choice(customer_groups),
            account_type=random.choice(['Individual', 'Business']),
            business_name=f'{first_names[index % len(first_names)]} Enterprises' if random.choice([True, False]) else None,
            phone=f'+2547{10000000 + index:08d}',
            alternative_contact=f'+2547{20000000 + index:08d}',
            credit_limit=Decimal(random.randint(10000, 500000)),
            created_by=admin_user,
        )
        
        return contact
