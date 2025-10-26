"""
Django management command to manually assign ESS permissions to staff role
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Assign ESS-related permissions to the staff role'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force reassignment of all permissions even if already assigned',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output of permission assignments',
        )

    def handle(self, *args, **options):
        force = options['force']
        verbose = options['verbose']
        
        self.stdout.write(
            self.style.SUCCESS('🔐 Starting ESS permission assignment to staff role...')
        )
        
        try:
            # Get or create the staff group
            staff_group, created = Group.objects.get_or_create(name='staff')
            if created:
                self.stdout.write(self.style.SUCCESS("✅ Created 'staff' group"))
            else:
                self.stdout.write("📋 Found existing 'staff' group")

            # Get ESS settings to determine which permissions should be enabled
            try:
                from hrm.attendance.models import ESSSettings
                ess_settings = ESSSettings.load()
                self.stdout.write("✅ Loaded ESS settings")
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"⚠️  Could not load ESS settings: {str(e)}. Using defaults.")
                )
                ess_settings = None

            # Define ESS permission mapping
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
            skipped_features = []
            
            for setting_field, permission_list in ess_permission_mapping.items():
                # Check if this feature is enabled in ESS settings
                is_enabled = getattr(ess_settings, setting_field, True) if ess_settings else True
                
                if is_enabled:
                    if verbose:
                        self.stdout.write(f"✅ Feature enabled: {setting_field}")
                    
                    for app_label, model_name, codename in permission_list:
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
                                    if verbose:
                                        self.stdout.write(f"  📌 Adding: {app_label}.{codename}")
                                elif not permission and verbose:
                                    self.stdout.write(
                                        self.style.WARNING(f"  ⚠️  Permission not found: {app_label}.{codename}")
                                    )
                        except Exception as e:
                            if verbose:
                                self.stdout.write(
                                    self.style.WARNING(f"  ⚠️  Error getting permission {app_label}.{codename}: {str(e)}")
                                )
                else:
                    skipped_features.append(setting_field)
                    if verbose:
                        self.stdout.write(
                            self.style.WARNING(f"⏭️  Feature disabled: {setting_field}")
                        )

            # Add basic employee permissions
            basic_staff_permissions = [
                ('hrm', 'employee', 'view_employee'),
                ('hrm', 'hrdetails', 'view_hrdetails'),
                ('hrm', 'personaldetails', 'view_personaldetails'),
            ]

            self.stdout.write("\n📋 Adding basic staff permissions...")
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
                            if verbose:
                                self.stdout.write(f"  📌 Adding basic: {app_label}.{codename}")
                except Exception as e:
                    if verbose:
                        self.stdout.write(
                            self.style.WARNING(f"  ⚠️  Error getting basic permission {app_label}.{codename}: {str(e)}")
                        )

            # Assign collected permissions to staff group
            if permissions_to_assign:
                current_permissions = set(staff_group.permissions.all())
                new_permissions = set(permissions_to_assign)
                
                if force:
                    staff_group.permissions.set(permissions_to_assign)
                    self.stdout.write(
                        self.style.SUCCESS(f"\n✅ Force assigned {len(permissions_to_assign)} permissions to 'staff' group")
                    )
                else:
                    permissions_added = new_permissions - current_permissions
                    if permissions_added:
                        staff_group.permissions.add(*permissions_to_assign)
                        self.stdout.write(
                            self.style.SUCCESS(f"\n✅ Added {len(permissions_added)} new permissions to 'staff' group")
                        )
                        self.stdout.write(f"   Total permissions: {len(new_permissions)}")
                    else:
                        self.stdout.write(
                            self.style.SUCCESS("\n✅ Staff group already has all required ESS permissions")
                        )
                        self.stdout.write(f"   Total permissions: {len(current_permissions)}")
            else:
                self.stdout.write(
                    self.style.WARNING("\n⚠️  No ESS permissions found to assign")
                )

            if skipped_features:
                self.stdout.write(
                    self.style.WARNING(f"\n⏭️  Skipped {len(skipped_features)} disabled features")
                )

            self.stdout.write(
                self.style.SUCCESS('\n🎉 ESS permission assignment completed!')
            )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\n❌ Error: {str(e)}')
            )
            import traceback
            if verbose:
                self.stdout.write(traceback.format_exc())

