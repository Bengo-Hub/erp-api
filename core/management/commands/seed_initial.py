"""
Initial Data Seeding Command
Seeds only essential data required for system operation:
- Superuser account
- User roles and permissions
- Default tax rates
- ESS settings
- Core reference data (regions, departments)
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from decimal import Decimal

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds initial required data for system operation (idempotent)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-superuser',
            action='store_true',
            help='Skip superuser creation'
        )
        parser.add_argument(
            '--skip-roles',
            action='store_true',
            help='Skip role and permission setup'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('INITIAL DATA SEEDING (Production Safe)'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

        try:
            with transaction.atomic():
                # 1. Create superuser account
                if not options.get('skip_superuser'):
                    self._create_superuser()

                # 2. Setup roles and permissions
                if not options.get('skip_roles'):
                    self._setup_roles()

                # 3. Setup ESS settings
                self._setup_ess_settings()

                # 4. Create default tax rates
                self._create_tax_rates()

                # 5. Seed core reference data (regions, departments)
                self._seed_core_reference_data()

                # 6. Apply RBAC provisioning
                self._apply_rbac()

            self.stdout.write(self.style.SUCCESS('\n' + '=' * 60))
            self.stdout.write(self.style.SUCCESS('✅ Initial data seeding completed successfully!'))
            self.stdout.write(self.style.SUCCESS('=' * 60))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Seeding failed: {str(e)}'))
            raise

    def _create_superuser(self):
        """Create superuser account if not exists"""
        self.stdout.write('\n1️⃣  Creating Superuser Account...')

        # Check if superuser exists
        admin = User.objects.filter(username='admin').first() or \
                User.objects.filter(email='admin@codevertexitsolutions.com').first()

        if admin:
            self.stdout.write(self.style.WARNING('   ⚠️  Superuser already exists'))
            self.stdout.write(f'   Username: {admin.username}')
            self.stdout.write(f'   Email: {admin.email}')
        else:
            admin = User.objects.create_superuser(
                username='admin',
                email='admin@codevertexitsolutions.com',
                password='Admin@2025!',
                first_name='System',
                last_name='Administrator'
            )
            self.stdout.write(self.style.SUCCESS('   ✅ Superuser created'))
            self.stdout.write(f'   Username: admin')
            self.stdout.write(f'   Password: Admin@2025!')
            self.stdout.write(f'   Email: admin@codevertexitsolutions.com')

    def _setup_roles(self):
        """Setup essential user roles with permissions"""
        self.stdout.write('\n2️⃣  Setting Up Roles & Permissions...')

        # Superusers group
        superusers_group, created = Group.objects.get_or_create(name='superusers')
        if created:
            # Assign all permissions to superusers
            all_permissions = Permission.objects.all()
            superusers_group.permissions.set(all_permissions)
            self.stdout.write(self.style.SUCCESS(f'   ✅ Created superusers group with {all_permissions.count()} permissions'))
        else:
            self.stdout.write('   ✅ Superusers group already exists')

        # Staff role with ESS permissions
        staff_group, created = Group.objects.get_or_create(name='staff')
        if created or staff_group.permissions.count() == 0:
            staff_permissions = self._get_staff_permissions()
            staff_group.permissions.set(staff_permissions)
            self.stdout.write(self.style.SUCCESS(f'   ✅ Staff role configured with {staff_permissions.count()} ESS permissions'))
        else:
            self.stdout.write(f'   ✅ Staff role already configured ({staff_group.permissions.count()} permissions)')

        # Essential management roles
        management_roles = [
            'hr_manager', 'finance_manager', 'procurement_manager',
            'sales_manager', 'operations_manager', 'ict_manager'
        ]

        for role_name in management_roles:
            role, created = Group.objects.get_or_create(name=role_name)
            if created:
                self.stdout.write(f'   ✅ Created role: {role_name}')

        self.stdout.write(self.style.SUCCESS(f'   ✅ {Group.objects.count()} roles configured'))

    def _get_staff_permissions(self):
        """Get ESS permissions for staff role"""
        permission_specs = [
            # Employee self-service
            ('employees', 'employee', 'view'),
            ('employees', 'contactdetails', 'view'),
            ('employees', 'contactdetails', 'change'),
            # Payroll
            ('payroll', 'payslip', 'view'),
            ('payroll', 'advances', 'view'),
            ('payroll', 'advances', 'add'),
            ('payroll', 'expenseclaims', 'view'),
            ('payroll', 'expenseclaims', 'add'),
            # Leave
            ('leave', 'leaverequest', 'view'),
            ('leave', 'leaverequest', 'add'),
            ('leave', 'leavebalance', 'view'),
            # Attendance
            ('attendance', 'timesheet', 'view'),
            ('attendance', 'timesheet', 'add'),
            ('attendance', 'timesheet', 'change'),
            ('attendance', 'timesheetentry', 'view'),
            ('attendance', 'timesheetentry', 'add'),
            ('attendance', 'timesheetentry', 'change'),
            ('attendance', 'attendancerecord', 'view'),
            # User account
            ('authmanagement', 'customuser', 'view'),
            ('authmanagement', 'customuser', 'change'),
            ('authmanagement', 'userpreferences', 'view'),
            ('authmanagement', 'userpreferences', 'change'),
        ]

        permissions = []
        for app_label, model_name, perm_type in permission_specs:
            codename = f'{perm_type}_{model_name}'
            perm = Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename
            ).first()
            if perm:
                permissions.append(perm)

        return permissions

    def _setup_ess_settings(self):
        """Create default ESS settings"""
        self.stdout.write('\n3️⃣  Setting Up ESS Settings...')

        try:
            from hrm.attendance.models import ESSSettings
            settings, created = ESSSettings.objects.get_or_create(pk=1)
            if created:
                settings.allow_payslip_view = True
                settings.allow_leave_application = True
                settings.allow_timesheet_application = True
                settings.require_password_change_on_first_login = True
                settings.save()
                self.stdout.write(self.style.SUCCESS('   ✅ ESS settings created'))
            else:
                self.stdout.write('   ✅ ESS settings already exist')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'   ⚠️  ESS settings: {str(e)}'))

    def _create_tax_rates(self):
        """Create default tax rates"""
        self.stdout.write('\n4️⃣  Creating Default Tax Rates...')

        try:
            from business.models import TaxRates
            
            tax_rates_data = [
                {'tax_name': 'VAT', 'percentage': Decimal('16.0'), 'is_default': True},
                {'tax_name': 'Zero Rated', 'percentage': Decimal('0.0'), 'is_default': False},
                {'tax_name': 'Exempt', 'percentage': Decimal('0.0'), 'is_default': False},
            ]

            for tax_data in tax_rates_data:
                tax, created = TaxRates.objects.get_or_create(
                    tax_name=tax_data['tax_name'],
                    defaults={
                        'percentage': tax_data['percentage'],
                        'is_default': tax_data['is_default']
                    }
                )
                if created:
                    self.stdout.write(f'   ✅ Created tax rate: {tax.tax_name} ({tax.percentage}%)')
                else:
                    self.stdout.write(f'   ✅ Tax rate exists: {tax.tax_name}')

        except Exception as e:
            self.stdout.write(self.style.WARNING(f'   ⚠️  Tax rates: {str(e)}'))

    def _seed_core_reference_data(self):
        """Seed essential core reference data"""
        self.stdout.write('\n5️⃣  Seeding Core Reference Data...')

        try:
            from core.models import Regions, Departments

            # Create essential regions
            regions_data = [
                {'name': 'Nairobi', 'code': 'NBI'},
                {'name': 'Mombasa', 'code': 'MBS'},
                {'name': 'Kisumu', 'code': 'KSM'},
            ]

            for region_data in regions_data:
                region, created = Regions.objects.get_or_create(
                    name=region_data['name'],
                    defaults={'code': region_data['code']}
                )
                if created:
                    self.stdout.write(f'   ✅ Created region: {region.name}')

            # Create essential departments
            departments_data = [
                {'title': 'Finance', 'code': 'FIN'},
                {'title': 'Human Resources', 'code': 'HR'},
                {'title': 'Information Technology', 'code': 'IT'},
                {'title': 'Operations', 'code': 'OPS'},
                {'title': 'Sales', 'code': 'SAL'},
            ]

            for dept_data in departments_data:
                dept, created = Departments.objects.get_or_create(
                    title=dept_data['title'],
                    defaults={'code': dept_data['code']}
                )
                if created:
                    self.stdout.write(f'   ✅ Created department: {dept.title}')

            self.stdout.write(self.style.SUCCESS('   ✅ Core reference data ready'))

        except Exception as e:
            self.stdout.write(self.style.WARNING(f'   ⚠️  Core reference data: {str(e)}'))

    def _apply_rbac(self):
        """Apply centralized RBAC provisioning"""
        self.stdout.write('\n6️⃣  Applying RBAC Provisioning...')

        try:
            from core.security import ensure_rbac_provisioned
            ensure_rbac_provisioned()
            self.stdout.write(self.style.SUCCESS('   ✅ RBAC provisioning applied'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'   ⚠️  RBAC provisioning: {str(e)}'))

