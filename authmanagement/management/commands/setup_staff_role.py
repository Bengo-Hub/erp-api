from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

class Command(BaseCommand):
    help = 'Delete and recreate staff role with proper ESS permissions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--list-only',
            action='store_true',
            help='Only list available permissions without creating role',
        )
        parser.add_argument(
            '--assign-demo-users',
            action='store_true',
            help='Auto-assign Staff role to users with "demo" in their email',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Setting up staff role with ESS permissions...'))
        
        # List all available permissions for debugging
        if options['list_only']:
            self.list_all_hrm_permissions()
            return
        
        # Delete existing staff roles (case-insensitive)
        existing_staff = Group.objects.filter(name__iexact='staff')
        if existing_staff.exists():
            count = existing_staff.count()
            self.stdout.write(self.style.WARNING(f'Deleting {count} existing staff role(s)...'))
            for group in existing_staff:
                users_count = group.user_set.count()
                self.stdout.write(f'  - {group.name} (with {users_count} users)')
            existing_staff.delete()
            self.stdout.write(self.style.SUCCESS('Deleted existing staff roles'))
        
        # Create new staff role
        staff_group = Group.objects.create(name='staff')
        self.stdout.write(self.style.SUCCESS('Created new staff role'))
        
        # Define comprehensive staff permissions across all key modules
        # Format: (app_label, model_name, permission_type)
        ess_permissions = [
            # ===== HRM - Employee & Personal Information =====
            ('employees', 'employee', 'view'),
            ('employees', 'hrdetails', 'view'),
            ('employees', 'hrdetails', 'change'),
            ('employees', 'contactdetails', 'view'),
            ('employees', 'contactdetails', 'change'),
            ('employees', 'employeebankaccount', 'view'),
            ('employees', 'employeebankaccount', 'change'),
            ('employees', 'nextofkin', 'view'),
            ('employees', 'nextofkin', 'add'),
            ('employees', 'nextofkin', 'change'),
            ('employees', 'contract', 'view'),
            ('employees', 'salarydetails', 'view'),
            ('employees', 'documents', 'view'),
            ('employees', 'documents', 'add'),
            ('employees', 'jobgroup', 'view'),
            ('employees', 'jobtitle', 'view'),
            ('employees', 'workersunion', 'view'),
            
            # ===== HRM - Payroll & Compensation =====
            ('payroll', 'payslip', 'view'),
            ('payroll', 'advances', 'view'),
            ('payroll', 'advances', 'add'),
            ('payroll', 'expenseclaims', 'view'),
            ('payroll', 'expenseclaims', 'add'),
            ('payroll', 'expenseclaims', 'change'),
            ('payroll', 'lossesanddamages', 'view'),
            ('payroll', 'lossesanddamages', 'add'),
            ('payroll', 'benefits', 'view'),
            ('payroll', 'deductions', 'view'),
            ('payroll', 'earnings', 'view'),
            ('payroll', 'employeloans', 'view'),
            ('payroll', 'claimitems', 'view'),
            ('payroll', 'expenseclaimsettings', 'view'),
            ('payroll', 'expensecode', 'view'),
            
            # ===== HRM - Leave Management =====
            ('leave', 'leavecategory', 'view'),
            ('leave', 'leaverequest', 'view'),
            ('leave', 'leaverequest', 'add'),
            ('leave', 'leaverequest', 'change'),
            ('leave', 'leavebalance', 'view'),
            ('leave', 'leaveentitlement', 'view'),
            ('leave', 'publicholiday', 'view'),
            ('leave', 'leavelog', 'view'),
            
            # ===== HRM - Time & Attendance =====
            ('attendance', 'timesheet', 'view'),
            ('attendance', 'timesheet', 'add'),
            ('attendance', 'timesheet', 'change'),
            ('attendance', 'timesheetentry', 'view'),
            ('attendance', 'timesheetentry', 'add'),
            ('attendance', 'timesheetentry', 'change'),
            ('attendance', 'timesheetentry', 'delete'),
            ('attendance', 'attendancerecord', 'view'),
            ('attendance', 'attendancerecord', 'add'),
            ('attendance', 'attendancerule', 'view'),
            ('attendance', 'workshift', 'view'),
            ('attendance', 'shiftrotation', 'view'),
            ('attendance', 'offday', 'view'),
            ('attendance', 'esssettings', 'view'),
            
            # ===== HRM - Training & Development =====
            ('training', 'trainingcourse', 'view'),
            ('training', 'trainingenrollment', 'view'),
            ('training', 'trainingenrollment', 'add'),
            ('training', 'trainingevaluation', 'view'),
            ('training', 'trainingevaluation', 'add'),
            
            # ===== HRM - Performance & Appraisals =====
            ('appraisals', 'appraisal', 'view'),
            ('appraisals', 'appraisalresponse', 'view'),
            ('appraisals', 'appraisalresponse', 'add'),
            ('appraisals', 'appraisalresponse', 'change'),
            ('appraisals', 'goal', 'view'),
            ('appraisals', 'goal', 'add'),
            ('appraisals', 'goal', 'change'),
            ('appraisals', 'appraisalcycle', 'view'),
            ('appraisals', 'appraisalquestion', 'view'),
            ('appraisals', 'appraisaltemplate', 'view'),
            ('appraisals', 'goalprogress', 'view'),
            
            # ===== HRM - Performance Management =====
            ('performance', 'performancemetric', 'view'),
            ('performance', 'performancereview', 'view'),
            ('performance', 'metriccategory', 'view'),
            ('performance', 'metrictarget', 'view'),
            ('performance', 'employeemetric', 'view'),
            ('performance', 'reviewmetric', 'view'),
            
            # ===== HRM - Recruitment (basic view access) =====
            ('recruitment', 'candidate', 'view'),
            ('recruitment', 'jobposting', 'view'),
            ('recruitment', 'application', 'view'),
            
            # ===== User Account Management =====
            ('authmanagement', 'customuser', 'view'),
            ('authmanagement', 'customuser', 'change'),
            ('authmanagement', 'userpreferences', 'view'),
            ('authmanagement', 'userpreferences', 'change'),
            
            # ===== Core - Reference Data (Read-Only) =====
            ('core', 'departments', 'view'),
            ('core', 'regions', 'view'),
            ('core', 'projects', 'view'),
            ('core', 'projectcategory', 'view'),
            ('core', 'location', 'view'),
            ('core', 'brandingsettings', 'view'),
            ('core', 'regionalsettings', 'view'),
            
            # ===== CRM - Basic Customer Interaction =====
            ('contacts', 'contact', 'view'),
            ('leads', 'lead', 'view'),
            ('campaigns', 'customergroup', 'view'),
            
            # ===== E-commerce - Product Viewing =====
            ('product', 'products', 'view'),
            ('product', 'category', 'view'),
            ('pos', 'sales', 'view'),
            
            # ===== Finance - Own Transactions =====
            ('expenses', 'expense', 'view'),
            ('expenses', 'expense', 'add'),
            ('reconciliation', 'transaction', 'view'),
            
            # ===== Notifications =====
            ('notifications', 'inappnotification', 'view'),
            ('notifications', 'usernotificationpreferences', 'view'),
            ('notifications', 'usernotificationpreferences', 'change'),
            ('notifications', 'usernotificationpreferences', 'delete'),
            ('notifications', 'notificationintegration', 'view'),
            
            # ===== Task Management =====
            ('task_management', 'task', 'view'),
            ('task_management', 'task', 'add'),
            ('task_management', 'task', 'change'),
        ]
        
        self.stdout.write(f'\nAttempting to assign {len(ess_permissions)} permissions...')
        
        # Collect permissions
        permissions_added = []
        permissions_not_found = []
        permissions_by_module = {}  # Track by module for better reporting
        
        for app_label, model_name, perm_type in ess_permissions:
            codename = f'{perm_type}_{model_name}'
            
            # Try to find the permission
            permission = Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename
            ).first()
            
            if permission:
                staff_group.permissions.add(permission)
                permissions_added.append(f'{app_label}.{codename}')
                
                # Track by module for reporting
                if app_label not in permissions_by_module:
                    permissions_by_module[app_label] = []
                permissions_by_module[app_label].append(codename)
            else:
                permissions_not_found.append(f'{app_label}.{codename}')
        
        # Display results organized by module
        self.stdout.write(self.style.SUCCESS(f'\n✓ Successfully assigned {len(permissions_added)} permissions to Staff role'))
        
        if permissions_by_module:
            self.stdout.write('\nPermissions by Module:')
            for module, perms in sorted(permissions_by_module.items()):
                self.stdout.write(f'\n  {module.upper()} ({len(perms)} permissions):')
                for perm in sorted(perms)[:10]:  # Show first 10
                    self.stdout.write(f'    • {perm}')
                if len(perms) > 10:
                    self.stdout.write(f'    ... and {len(perms) - 10} more')
        
        if permissions_not_found:
            self.stdout.write(self.style.WARNING(f'\n⚠ {len(permissions_not_found)} permissions not found (models may not be migrated yet):'))
            for perm in sorted(permissions_not_found):
                self.stdout.write(f'  • {perm}')
        
        # Show total
        total_perms = staff_group.permissions.count()
        self.stdout.write(self.style.SUCCESS(f'\n✓ staff role now has {total_perms} total permissions'))
        
        # Auto-assign to demo users if requested
        if options['assign_demo_users']:
            from authmanagement.models import CustomUser
            demo_users = CustomUser.objects.filter(
                Q(email__icontains='demo') | Q(username__icontains='demo') | Q(is_staff=True)
            ).exclude(
                Q(is_superuser=True) | Q(groups__name__iexact='superusers')
            )
            
            if demo_users.exists():
                self.stdout.write(self.style.SUCCESS(f'\n✓ Assigning staff role to {demo_users.count()} demo users:'))
                for user in demo_users:
                    user.groups.add(staff_group)
                    self.stdout.write(f'  • {user.username} ({user.email})')
            else:
                self.stdout.write(self.style.WARNING('\n⚠ No demo users found'))
        
        # Show users who will be affected
        staff_users = staff_group.user_set.all()
        if staff_users.exists():
            self.stdout.write(self.style.SUCCESS(f'\n✓ {staff_users.count()} users have the staff role:'))
            for user in staff_users:
                self.stdout.write(f'  • {user.username} ({user.email})')
        else:
            self.stdout.write(self.style.WARNING('\n⚠ No users currently have the staff role'))
        
        # Show what HRM permissions actually exist for debugging
        self.stdout.write(self.style.SUCCESS('\n\nDEBUG: Checking what HRM permissions actually exist...'))
        actual_hrm_perms = Permission.objects.filter(
            content_type__app_label='hrm'
        ).select_related('content_type').order_by('content_type__model', 'codename')
        
        if actual_hrm_perms.exists():
            self.stdout.write(f'Found {actual_hrm_perms.count()} HRM permissions:')
            current_model = None
            for perm in actual_hrm_perms[:20]:  # Show first 20
                model = perm.content_type.model
                if model != current_model:
                    self.stdout.write(f'\n  {model}:')
                    current_model = model
                self.stdout.write(f'    - {perm.codename}')
            if actual_hrm_perms.count() > 20:
                self.stdout.write(f'\n  ... and {actual_hrm_perms.count() - 20} more')
        else:
            self.stdout.write(self.style.ERROR('  ✗ No HRM permissions found! Run migrations first:'))
            self.stdout.write('    python manage.py makemigrations hrm')
            self.stdout.write('    python manage.py migrate hrm')
    
    def list_all_hrm_permissions(self):
        """List all HRM-related permissions for debugging"""
        self.stdout.write(self.style.SUCCESS('All HRM-related permissions in database:'))
        
        hrm_permissions = Permission.objects.filter(
            Q(content_type__app_label='hrm') | 
            Q(content_type__app_label='authmanagement') |
            Q(content_type__app_label='core')
        ).select_related('content_type').order_by('content_type__app_label', 'content_type__model', 'codename')
        
        current_app = None
        current_model = None
        
        for perm in hrm_permissions:
            app = perm.content_type.app_label
            model = perm.content_type.model
            
            if app != current_app:
                self.stdout.write(f'\n{app.upper()}:')
                current_app = app
                current_model = None
            
            if model != current_model:
                self.stdout.write(f'  {model}:')
                current_model = model
            
            self.stdout.write(f'    - {perm.codename} ({perm.name})')
        
        self.stdout.write(self.style.SUCCESS(f'\nTotal: {hrm_permissions.count()} permissions'))

