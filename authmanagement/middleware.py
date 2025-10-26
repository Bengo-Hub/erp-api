from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from authmanagement.models import CustomUser
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError
import logging

from business.models import BusinessLocation, Branch
from crm.contacts.models import Contact

logger = logging.getLogger(__name__)

class SiteWideConfigs:
    def __init__(self, get_response):
        self.get_response = get_response
        # Class-level flags to track initialization status
        self._roles_initialized = False
        self._admin_user_initialized = False
        self._walkin_users_initialized = False
        self._ess_permissions_assigned = False
        self._ess_settings_initialized = False

    def __call__(self, request):
        # Only run initialization logic once per server startup
        if not self._roles_initialized:
            self._initialize_roles_and_permissions()
        
        if not self._admin_user_initialized:
            self._initialize_admin_user()
        
        # Always check if admin user exists, even if marked as initialized
        if self._admin_user_initialized:
            self._ensure_admin_user_exists()
        
        if not self._walkin_users_initialized:
            self._initialize_walkin_users()
        
        # Assign ESS permissions to staff role (run once when superuser logs in)
        if not self._ess_permissions_assigned and request.user.is_authenticated and request.user.is_superuser:
            self._assign_ess_permissions_to_staff()
            self._ess_permissions_assigned = True
        
        # Initialize ESS settings (run once)
        if not self._ess_settings_initialized:
            self._initialize_ess_settings()
            self._ess_settings_initialized = True
        
        response = self.get_response(request)
        return response

    def _initialize_roles_and_permissions(self):
        """Initialize roles and permissions only if they don't exist"""
        try:
            # Check if core roles already exist (case-insensitive)
            existing_roles = Group.objects.all()
            if existing_roles.exists():
                # Ensure no duplicate staff roles (case-insensitive check)
                staff_groups = [g for g in existing_roles if g.name.lower() == 'staff']
                if len(staff_groups) > 1:
                    # Keep only the first one, delete duplicates
                    primary_staff = staff_groups[0]
                    for duplicate in staff_groups[1:]:
                        logger.warning(f"Removing duplicate staff group: {duplicate.name}")
                        # Transfer any users from duplicate to primary
                        for user in duplicate.user_set.all():
                            user.groups.add(primary_staff)
                        duplicate.delete()
                
                self._roles_initialized = True
                # Still assign permissions to existing staff role
                self._assign_staff_permissions()
                return
            
            # Create basic roles with case-sensitive names
            roles = ['Admin', 'Staff', 'Procurement Manager', 'HR Manager']
            for role in roles:
                # Check if role exists (case-insensitive)
                existing = Group.objects.filter(name__iexact=role).first()
                if not existing:
                    Group.objects.create(name=role)
                    logger.info(f"Created role: {role}")
                else:
                    logger.info(f"Role already exists: {existing.name}")
            
            # Ensure 'superusers' group exists
            superusers_group = Group.objects.filter(name__iexact='superusers').first()
            if not superusers_group:
                superusers_group = Group.objects.create(name='Superusers')
                logger.info("Created Superusers group")
            
            # Assign all permissions to 'superusers' group
            if not superusers_group.permissions.exists():
                # Retrieve all permissions from all models
                content_types = ContentType.objects.all()
                permissions = Permission.objects.filter(content_type__in=content_types)
                superusers_group.permissions.set(permissions)
                logger.info(f"Assigned {permissions.count()} permissions to Superusers group")
            
            # Assign permissions to staff role
            self._assign_staff_permissions()
            
            self._roles_initialized = True
            logger.info("Roles and permissions initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing roles and permissions: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # Mark as initialized to prevent repeated attempts
            self._roles_initialized = True

    def _assign_staff_permissions(self):
        """
        Assign comprehensive permissions to the Staff role.
        This ensures staff members have appropriate access to ESS and key modules.
        """
        try:
            # Get the staff group (case-insensitive)
            staff_group = Group.objects.filter(name__iexact='staff').first()
            if not staff_group:
                logger.warning("Staff group not found. Creating it now...")
                staff_group = Group.objects.create(name='Staff')
                logger.info("Created Staff group")

            # Get all available permissions
            all_permissions = Permission.objects.all()
            logger.info(f"Total available permissions in database: {all_permissions.count()}")

            # Define comprehensive staff permissions by module
            # Format: (app_label, model_name_pattern, permission_actions)
            staff_permission_patterns = [
                # ===== HRM - Employee & Personal Information =====
                ('employees', 'employee', ['view']),
                ('employees', 'hrdetails', ['view', 'change']),
                ('employees', 'contactdetails', ['view', 'change']),
                ('employees', 'employeebankaccount', ['view', 'change']),
                ('employees', 'nextofkin', ['view', 'add', 'change']),
                ('employees', 'contract', ['view']),
                ('employees', 'salarydetails', ['view']),
                ('employees', 'documents', ['view', 'add']),
                ('employees', 'jobgroup', ['view']),
                ('employees', 'jobtitle', ['view']),
                ('employees', 'workersunion', ['view']),
                
                # ===== HRM - Payroll & Compensation =====
                ('payroll', 'payslip', ['view']),
                ('payroll', 'advances', ['view', 'add']),
                ('payroll', 'expenseclaims', ['view', 'add', 'change']),
                ('payroll', 'lossesanddamages', ['view', 'add']),
                ('payroll', 'benefits', ['view']),
                ('payroll', 'deductions', ['view']),
                ('payroll', 'earnings', ['view']),
                ('payroll', 'employeloans', ['view']),
                ('payroll', 'claimitems', ['view']),
                ('payroll', 'expenseclaimsettings', ['view']),
                ('payroll', 'expensecode', ['view']),
                
                # ===== HRM - Leave Management =====
                ('leave', 'leavecategory', ['view']),
                ('leave', 'leaverequest', ['view', 'add', 'change']),
                ('leave', 'leavebalance', ['view']),
                ('leave', 'leaveentitlement', ['view']),
                ('leave', 'publicholiday', ['view']),
                ('leave', 'leavelog', ['view']),
                
                # ===== HRM - Time & Attendance =====
                ('attendance', 'timesheet', ['view', 'add', 'change']),
                ('attendance', 'timesheetentry', ['view', 'add', 'change', 'delete']),
                ('attendance', 'attendancerecord', ['view', 'add']),
                ('attendance', 'attendancerule', ['view']),
                ('attendance', 'workshift', ['view']),
                ('attendance', 'shiftrotation', ['view']),
                ('attendance', 'offday', ['view']),
                ('attendance', 'esssettings', ['view']),
                
                # ===== HRM - Training & Development =====
                ('training', 'trainingcourse', ['view']),
                ('training', 'trainingenrollment', ['view', 'add']),
                ('training', 'trainingevaluation', ['view', 'add']),
                
                # ===== HRM - Performance & Appraisals =====
                ('appraisals', 'appraisal', ['view']),
                ('appraisals', 'appraisalresponse', ['view', 'add', 'change']),
                ('appraisals', 'goal', ['view', 'add', 'change']),
                ('appraisals', 'appraisalcycle', ['view']),
                ('appraisals', 'appraisalquestion', ['view']),
                ('appraisals', 'appraisaltemplate', ['view']),
                ('appraisals', 'goalprogress', ['view']),
                
                # ===== HRM - Performance Management =====
                ('performance', 'performancemetric', ['view']),
                ('performance', 'performancereview', ['view']),
                ('performance', 'metriccategory', ['view']),
                ('performance', 'metrictarget', ['view']),
                ('performance', 'employeemetric', ['view']),
                ('performance', 'reviewmetric', ['view']),
                
                # ===== HRM - Recruitment (basic view access) =====
                ('recruitment', 'candidate', ['view']),
                ('recruitment', 'jobposting', ['view']),
                ('recruitment', 'application', ['view']),
                
                # ===== User Management - Own Account =====
                ('authmanagement', 'customuser', ['view', 'change']),
                ('authmanagement', 'userpreferences', ['view', 'change']),
                
                # ===== Core - Reference Data =====
                ('core', 'departments', ['view']),
                ('core', 'regions', ['view']),
                ('core', 'projects', ['view']),
                ('core', 'projectcategory', ['view']),
                ('core', 'location', ['view']),
                ('core', 'brandingsettings', ['view']),
                ('core', 'regionalsettings', ['view']),
                
                # ===== CRM - Basic Access =====
                ('contacts', 'contact', ['view']),
                ('leads', 'lead', ['view']),
                ('campaigns', 'customergroup', ['view']),
                
                # ===== E-commerce - Basic Product View =====
                ('product', 'products', ['view']),
                ('product', 'category', ['view']),
                ('pos', 'sales', ['view']),
                
                # ===== Finance - Own Transactions =====
                ('expenses', 'expense', ['view', 'add']),
                ('reconciliation', 'transaction', ['view']),
                
                # ===== Notifications =====
                ('notifications', 'inappnotification', ['view']),
                ('notifications', 'usernotificationpreferences', ['view', 'change', 'delete']),
                ('notifications', 'notificationintegration', ['view']),
                
                # ===== Task Management =====
                ('task_management', 'task', ['view', 'add', 'change']),
            ]

            # Collect permissions to assign
            permissions_to_assign = set()
            
            for app_label, model_pattern, actions in staff_permission_patterns:
                for action in actions:
                    # Try different codename patterns
                    codename_variants = [
                        f'{action}_{model_pattern}',
                        f'{action}_{model_pattern.lower()}',
                    ]
                    
                    for codename in codename_variants:
                        # Find permissions matching this pattern
                        matching_perms = all_permissions.filter(
                            content_type__app_label=app_label,
                            codename=codename
                        )
                        
                        for perm in matching_perms:
                            permissions_to_assign.add(perm)
                            logger.debug(f"Adding permission: {app_label}.{codename}")

            # Convert set to list
            permissions_list = list(permissions_to_assign)
            
            # Assign collected permissions to staff group
            if permissions_list:
                # Get current permissions
                current_permissions = set(staff_group.permissions.all())
                new_permissions = set(permissions_list)
                
                # Add new permissions
                permissions_added = new_permissions - current_permissions
                if permissions_added:
                    staff_group.permissions.add(*permissions_added)
                    logger.info(f"Assigned {len(permissions_added)} new permissions to Staff group")
                else:
                    logger.debug("Staff group already has all required permissions")
                    
                logger.info(f"Staff group now has {staff_group.permissions.count()} total permissions")
                
                # Log summary by category
                if permissions_added:
                    logger.info(f"Newly assigned {len(permissions_added)} permissions to Staff group")
            else:
                logger.warning("No permissions found to assign to Staff group - models may not be migrated yet")

        except Exception as e:
            logger.error(f"Error assigning permissions to Staff role: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

    def _initialize_admin_user(self):
        """Initialize admin user only if it doesn't exist"""
        try:
            # Check if admin user already exists
            if CustomUser.objects.filter(username='admin').exists() or CustomUser.objects.filter(email='admin@codevertexitsolutions.com').exists():
                self._admin_user_initialized = True
                return
            
            # Create new admin user
            admin_user = CustomUser.objects.create(
                username='admin',
                email='admin@codevertexitsolutions.com',
                password=make_password('Demo@2020!'),
                first_name='Super',
                middle_name='',
                last_name='User',
                is_active=True,
                is_staff=True,
                is_superuser=True
            )
            logger.info(f"Created new admin user: {admin_user.username}")
            
            # Add admin user to superusers group (case-insensitive)
            superusers_group = Group.objects.filter(name__iexact='superusers').first()
            if superusers_group:
                admin_user.groups.add(superusers_group)
                logger.info(f"Added admin user to superusers group: {admin_user.username}")
            else:
                logger.warning("Superusers group not found when adding admin user")
            
            self._admin_user_initialized = True
            logger.info("Admin user initialization completed successfully")
            
        except IntegrityError as e:
            logger.error(f"Error creating admin user: {str(e)}")
            # Try to get existing admin user
            admin_user = CustomUser.objects.filter(username='admin').first()
            if not admin_user:
                admin_user = CustomUser.objects.filter(email='admin@codevertexitsolutions.com').first()
            
            if admin_user:
                # Ensure admin user is in superusers group (case-insensitive)
                superusers_group = Group.objects.filter(name__iexact='superusers').first()
                if superusers_group and not admin_user.groups.filter(name__iexact='superusers').exists():
                    admin_user.groups.add(superusers_group)
                    logger.info(f"Added existing admin user to superusers group: {admin_user.username}")
            
            # Mark as initialized to prevent repeated attempts
            self._admin_user_initialized = True
            
        except Exception as e:
            logger.error(f"Error initializing admin user: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._admin_user_initialized = True

    def _ensure_admin_user_exists(self):
        """Ensure admin user exists, reset flag if not"""
        try:
            if not CustomUser.objects.filter(username='admin').exists() and not CustomUser.objects.filter(email='admin@codevertexitsolutions.com').exists():
                logger.warning("Admin user not found despite being marked as initialized. Resetting flag.")
                self._admin_user_initialized = False
        except Exception as e:
            logger.error(f"Error checking admin user existence: {str(e)}")
            self._admin_user_initialized = False

    def _initialize_walkin_users(self):
        """Initialize walk-in users only if they don't exist"""
        try:
            # Check if walk-in users already exist
            if CustomUser.objects.filter(email__icontains='walkin').exists():
                self._walkin_users_initialized = True
                return
            
            # Process business branches and create walk-in users
            for branch in Branch.objects.select_related('business', 'location').all():
                try:
                    if branch.business and branch.location:
                        business_name = branch.business.name
                        # Create walk in customer
                        email = f'walkin{business_name.replace(" ","_").lower()}'
                        user = CustomUser.objects.filter(email__icontains=email).first()
                        if user is None:
                            try:
                                walk_in_user, created = CustomUser.objects.update_or_create(
                                    email=f'walkin{business_name.replace(" ","_").lower()}{branch.id}@gmail.com',
                                    defaults={
                                        "username": f'walkin{business_name.replace(" ","_").lower()}',
                                        "first_name": 'Walk-In',
                                        "last_name": business_name.replace(" ","_").lower(),
                                        "phone": '07000000000',
                                        "password": make_password("@User123"),
                                        "is_active": True
                                    }
                                )
                                walk_in_user.save()
                                # Add to admin group (case-insensitive)
                                admin_group = Group.objects.filter(name__iexact='admin').first()
                                if admin_group:
                                    walk_in_user.groups.add(admin_group)
                                walk_in_user.save()
                                
                                # Create contact for walk-in user
                                Contact.objects.update_or_create(
                                    user=walk_in_user,
                                    contact_id=f'C{branch.id}000001',
                                    defaults={
                                        "branch": branch,  # Use the branch object directly
                                        "contact_type": 'Customers',
                                        "account_type": 'Individual',
                                        "designation": 'Other',
                                        "credit_limit": 0,
                                    }
                                )
                                logger.info(f"Created walk-in user for business: {business_name}")
                            except IntegrityError as e:
                                logger.error(f"Error creating walk-in user for business {business_name}: {str(e)}")
                                continue
                except Exception as e:
                    # Log the error but continue processing other locations
                    logger.error(f"Error processing business branch {branch.id}: {str(e)}")
                    continue
            
            self._walkin_users_initialized = True
            logger.info("Walk-in users initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing walk-in users: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._walkin_users_initialized = True

    def _assign_ess_permissions_to_staff(self):
        """
        Auto-assign ESS-related permissions to the 'staff' role based on ESS settings.
        This ensures staff members have appropriate permissions for ESS features.
        """
        try:
            # Get or create the staff group
            staff_group, created = Group.objects.get_or_create(name='staff')
            if created:
                logger.info("Created 'staff' group")

            # Get ESS settings to determine which permissions should be enabled
            try:
                from hrm.attendance.models import ESSSettings
                ess_settings = ESSSettings.load()
            except Exception as e:
                logger.warning(f"Could not load ESS settings: {str(e)}. Using defaults.")
                # Use default permissions if ESS settings not available
                ess_settings = None

            # Define ESS permission mapping: setting_field -> (app_label, model, permission_codename)
            ess_permission_mapping = {
                'allow_payslip_view': [
                    ('hrm', 'payroll', 'view_payroll'),
                    ('hrm', 'payslip', 'view_payslip'),
                ],
                'allow_leave_application': [
                    ('hrm', 'leave', 'add_leave'),
                    ('hrm', 'leave', 'view_leave'),
                    ('hrm', 'leaveapplication', 'add_leaveapplication'),
                    ('hrm', 'leaveapplication', 'view_leaveapplication'),
                ],
                'allow_timesheet_application': [
                    ('hrm', 'timesheet', 'add_timesheet'),
                    ('hrm', 'timesheet', 'view_timesheet'),
                ],
                'allow_overtime_application': [
                    ('hrm', 'overtime', 'add_overtime'),
                    ('hrm', 'overtime', 'view_overtime'),
                ],
                'allow_advance_salary_application': [
                    ('hrm', 'advancepay', 'add_advancepay'),
                    ('hrm', 'advancepay', 'view_advancepay'),
                    ('hrm', 'advance', 'add_advance'),
                    ('hrm', 'advance', 'view_advance'),
                ],
                'allow_losses_damage_submission': [
                    ('hrm', 'lossesdamages', 'add_lossesdamages'),
                    ('hrm', 'lossesdamages', 'view_lossesdamages'),
                ],
                'allow_expense_claims_application': [
                    ('hrm', 'expenseclaim', 'add_expenseclaim'),
                    ('hrm', 'expenseclaim', 'view_expenseclaim'),
                ],
            }

            # Collect permissions to assign based on ESS settings
            permissions_to_assign = []
            
            for setting_field, permission_list in ess_permission_mapping.items():
                # Check if this feature is enabled in ESS settings
                is_enabled = getattr(ess_settings, setting_field, True) if ess_settings else True
                
                if is_enabled:
                    for app_label, model_name, codename in permission_list:
                        try:
                            # Try to get the content type and permission
                            content_type = ContentType.objects.filter(
                                app_label=app_label,
                                model=model_name
                            ).first()
                            
                            if content_type:
                                permission = Permission.objects.filter(
                                    content_type=content_type,
                                    codename=codename
                                ).first()
                                
                                if permission and permission not in permissions_to_assign:
                                    permissions_to_assign.append(permission)
                        except Exception as e:
                            # Permission might not exist yet if models haven't been created
                            logger.debug(f"Permission {app_label}.{codename} not found: {str(e)}")

            # Add basic employee permissions that all staff should have
            basic_staff_permissions = [
                ('hrm', 'employee', 'view_employee'),  # View their own employee record
                ('hrm', 'hrdetails', 'view_hrdetails'),  # View their HR details
                ('hrm', 'personaldetails', 'view_personaldetails'),  # View personal details
            ]

            for app_label, model_name, codename in basic_staff_permissions:
                try:
                    content_type = ContentType.objects.filter(
                        app_label=app_label,
                        model=model_name
                    ).first()
                    
                    if content_type:
                        permission = Permission.objects.filter(
                            content_type=content_type,
                            codename=codename
                        ).first()
                        
                        if permission and permission not in permissions_to_assign:
                            permissions_to_assign.append(permission)
                except Exception as e:
                    logger.debug(f"Basic permission {app_label}.{codename} not found: {str(e)}")

            # Assign collected permissions to staff group
            if permissions_to_assign:
                current_permissions = set(staff_group.permissions.all())
                new_permissions = set(permissions_to_assign)
                
                # Only update if there are new permissions to add
                if new_permissions - current_permissions:
                    staff_group.permissions.add(*permissions_to_assign)
                    logger.info(f"Assigned {len(permissions_to_assign)} ESS-related permissions to 'staff' group")
                else:
                    logger.debug("Staff group already has all required ESS permissions")
            else:
                logger.warning("No ESS permissions found to assign to staff group")

        except Exception as e:
            logger.error(f"Error assigning ESS permissions to staff role: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _initialize_ess_settings(self):
        """
        Initialize ESS (Employee Self-Service) Settings.
        Creates singleton settings instance if it doesn't exist.
        """
        try:
            from hrm.attendance.models import ESSSettings
            
            # Check if ESS settings already exist
            if ESSSettings.objects.exists():
                logger.info("ESS settings already initialized")
                return
            
            # Create ESS settings using singleton pattern
            settings = ESSSettings.load()
            
            # Enable all ESS features by default for better UX
            settings.allow_payslip_view = True
            settings.allow_leave_application = True
            settings.allow_timesheet_application = True
            settings.allow_overtime_application = True
            settings.allow_advance_salary_application = True
            settings.allow_losses_damage_submission = True
            settings.allow_expense_claims_application = True
            settings.save()
            
            logger.info("ESS settings initialized successfully with all features enabled")
            
        except Exception as e:
            logger.warning(f"Could not initialize ESS settings: {str(e)}")
            logger.debug("ESS settings will use defaults until migrations are run")
            # Don't raise - this is not critical for startup
