from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from business.models import (
    BusinessLocation, Branch, TaxRates, 
    ProductSettings, SaleSettings, PrefixSettings, ServiceTypes
)
from authmanagement.models import CustomUser
from business.models import BusinessLocation, Branch, Bussiness
User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds business data including settings, tax rates, and other business configurations with single business setup'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing data before seeding',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing data...')
            self.clear_data()

        self.stdout.write(self.style.SUCCESS('Starting to seed business data with single business setup...'))
        
        # Ensure admin user exists and has proper permissions
        admin_user = self._ensure_admin_user()
        
        # Create or reuse single business "codevertex it solutions" with one location and one branch
        business, location, branch = self._create_single_business_setup(admin_user)
        
        # Create tax rates
        tax_rates = self.create_tax_rates(business)
        
        # Create product settings
        product_settings = self.create_product_settings(business)
        
        # Create sale settings
        sale_settings = self.create_sale_settings(business, tax_rates)
        
        # Create prefix settings
        prefix_settings = self.create_prefix_settings(business)
        
        # Create service types
        service_types = self.create_service_types(business)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Business data seeding completed successfully!\n'
                f'- Business: {business.name}\n'
                f'- Location: {location.city}\n'
                f'- Branch: {branch.name}\n'
                f'- {len(tax_rates)} tax rates created\n'
                f'- {len(service_types)} service types created\n'
                f'- Admin user assigned to superusers group with all permissions'
            )
        )

    def clear_data(self):
        """Clear existing data."""
        Branch.objects.all().delete()
        TaxRates.objects.all().delete()
        ProductSettings.objects.all().delete()
        SaleSettings.objects.all().delete()
        PrefixSettings.objects.all().delete()
        ServiceTypes.objects.all().delete()

    def _ensure_admin_user(self):
        """Ensure admin user exists and has proper permissions."""
        admin_user = User.objects.filter(username='admin').first() or User.objects.filter(email='admin@codevertexitsolutions.com').first()
        if not admin_user:
            admin_user = User.objects.create_superuser(
                username='admin', 
                email='admin@codevertexitsolutions.com', 
                password='Admin@2025!',
                first_name='System',
                last_name='Administrator',
            )
            self.stdout.write(self.style.SUCCESS('✓ Created admin user (username: admin)'))
        else:
            self.stdout.write(self.style.SUCCESS('✓ Admin user already exists - leaving as-is'))
        
        # Ensure superusers group exists
        superusers_group, created = Group.objects.get_or_create(name='superusers')
        if created:
            self.stdout.write(self.style.SUCCESS('Created superusers group'))
        
        # Add admin user to superusers group
        admin_user.groups.add(superusers_group)
        
        # Assign all permissions to superusers group
        all_permissions = Permission.objects.all()
        superusers_group.permissions.set(all_permissions)
        
        self.stdout.write(self.style.SUCCESS(f'Assigned {all_permissions.count()} permissions to superusers group'))
        
        return admin_user

    def _create_single_business_setup(self, admin_user):
        """Create or reuse business 'Codevertex IT Solutions' with one main branch only."""
        name = 'Codevertex IT Solutions'
        business = Bussiness.objects.filter(name__iexact=name).first()
        if not business:
            business = Bussiness.objects.create(
                name=name,
                start_date='2024-01-01',
                currency='KES',
                kra_number='A123456789X',
                business_type='limited_company',
                county='Nairobi',
                owner=admin_user
            )
            self.stdout.write(self.style.SUCCESS(f'Created business: {business.name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Reusing existing business: {business.name}'))

        # Ensure a single main location exists
        location = BusinessLocation.objects.filter(default=True).first()
        if not location:
            location = BusinessLocation.objects.create(
                city='Nairobi',
                county='Nairobi',
                state='KE',
                country='KE',
                zip_code='00100',
                postal_code='00100',
                website='https://www.codevertexafrica.com',
                default=True,
                is_active=True
            )

        # Ensure a single main branch exists (idempotent; reuse by unique branch_code)
        existing_by_code = Branch.objects.filter(branch_code='HQ-001').first()
        if existing_by_code and existing_by_code.business_id != business.id:
            main_branch = existing_by_code  # Reuse existing to avoid unique conflicts
        else:
            main_branch, _ = Branch.objects.get_or_create(
                branch_code='HQ-001',
                defaults={
                    'business': business,
                    'location': location,
                    'name': 'HQ',
                    'is_active': True,
                    'is_main_branch': True
                }
            )

        # Update business location to point to main branch location
        if not business.location_id:
            business.location = location
            business.save()
        
        return business, location, main_branch

    def create_tax_rates(self, business):
        """Create tax rates for the business."""
        tax_rates_data = [
            {'tax_name': 'VAT', 'percentage': 16.0, 'tax_number': 'T001'},
            {'tax_name': 'Withholding Tax', 'percentage': 5.0, 'tax_number': 'T002'},
            {'tax_name': 'Corporate Tax', 'percentage': 30.0, 'tax_number': 'T003'},
            {'tax_name': 'PAYE', 'percentage': 30.0, 'tax_number': 'T004'},
            {'tax_name': 'NHIF', 'percentage': 1.5, 'tax_number': 'T005'},
            {'tax_name': 'NSSF', 'percentage': 6.0, 'tax_number': 'T006'}
        ]
        
        tax_rates = []
        for tax_data in tax_rates_data:
            # TaxRates.tax_number is globally unique; reuse by tax_number to avoid unique constraint errors
            tax_rate = TaxRates.objects.filter(tax_number=tax_data['tax_number']).first()
            created = False
            if not tax_rate:
                tax_rate = TaxRates.objects.create(
                    business=business,
                    tax_name=tax_data['tax_name'],
                    tax_number=tax_data['tax_number'],
                    percentage=tax_data['percentage']
                )
                created = True
            else:
                # Ensure it points to current business and has correct name/percentage
                update_fields = []
                if tax_rate.business_id != business.id:
                    tax_rate.business = business
                    update_fields.append('business')
                if tax_rate.tax_name != tax_data['tax_name']:
                    tax_rate.tax_name = tax_data['tax_name']
                    update_fields.append('tax_name')
                if tax_rate.percentage != tax_data['percentage']:
                    tax_rate.percentage = tax_data['percentage']
                    update_fields.append('percentage')
                if update_fields:
                    tax_rate.save(update_fields=update_fields)
            tax_rates.append(tax_rate)
            if created:
                self.stdout.write(f'Created tax rate: {tax_rate.tax_name} ({tax_rate.percentage}%)')
        
        return tax_rates

    def create_product_settings(self, business):
        """Create product settings for the business."""
        product_settings, created = ProductSettings.objects.get_or_create(
            business=business,
            defaults={
                'default_unit': 'Piece(s)',
                'enable_warranty': True,
                'enable_product_expiry': True,
                'stop_selling_days_before_expiry': 30,
                'sku_prefix': 'BNG'
            }
        )
        
        if created:
            self.stdout.write('Created product settings')
        
        return [product_settings]

    def create_sale_settings(self, business, tax_rates):
        """Create sale settings for the business."""
        sale_settings, created = SaleSettings.objects.get_or_create(
            business=business,
            defaults={
                'default_discount': 0.00,
                'default_tax': tax_rates[0] if tax_rates else None  # VAT
            }
        )
        
        if created:
            self.stdout.write('Created sale settings')
        
        return [sale_settings]

    def create_prefix_settings(self, business):
        """Create prefix settings for the business."""
        prefix_settings, created = PrefixSettings.objects.get_or_create(
            business=business,
            defaults={
                'purchase': 'P',
                'purchase_order': 'PO',
                'purchase_return': 'PRT',
                'purchase_requisition': 'PRQ',
                'stock_transfer': 'ST',
                'sale_return': 'SR',
                'expense': 'EP',
                'business_location': 'BL'
            }
        )
        
        if created:
            self.stdout.write('Created prefix settings')
        
        return [prefix_settings]

    def create_service_types(self, business):
        """Create service types for the business."""
        service_types_data = [
            'Consulting',
            'Training',
            'Support',
            'Implementation',
            'Custom Development',
            'Integration',
            'Maintenance',
            'Hosting',
            'Licensing',
            'Professional Services'
        ]
        
        service_types = []
        for service_name in service_types_data:
            service_type, created = ServiceTypes.objects.get_or_create(
                business=business,
                name=service_name,
                defaults={
                    'description': f'{service_name} services',
                    'packing_charge_type': 'Fixed',
                    'packing_charge': 0
                }
            )
            service_types.append(service_type)
            if created:
                self.stdout.write(f'Created service type: {service_type.name}')
        
        return service_types
