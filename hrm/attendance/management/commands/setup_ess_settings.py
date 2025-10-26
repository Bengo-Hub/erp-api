from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group

class Command(BaseCommand):
    help = 'Initialize ESS (Employee Self-Service) Settings'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Reset ESS settings to defaults',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Initializing ESS Settings...'))
        
        try:
            from hrm.attendance.models import ESSSettings
            
            # Check if ESS settings exist
            existing = ESSSettings.objects.first()
            
            if options['reset'] and existing:
                self.stdout.write(self.style.WARNING('Resetting existing ESS settings...'))
                existing.delete()
                existing = None
            
            if existing:
                self.stdout.write(self.style.WARNING('ESS Settings already exist'))
                settings = existing
            else:
                # Create new ESS settings using the load() method (singleton pattern)
                settings = ESSSettings.load()
                self.stdout.write(self.style.SUCCESS('Created ESS Settings'))
            
            # Display current settings
            self.stdout.write('\n' + self.style.SUCCESS('Current ESS Settings:'))
            self.stdout.write(f'  • Enable Shift-Based Restrictions: {settings.enable_shift_based_restrictions}')
            self.stdout.write(f'  • Allow Payslip View: {settings.allow_payslip_view}')
            self.stdout.write(f'  • Allow Leave Application: {settings.allow_leave_application}')
            self.stdout.write(f'  • Allow Timesheet Application: {settings.allow_timesheet_application}')
            self.stdout.write(f'  • Allow Overtime Application: {settings.allow_overtime_application}')
            self.stdout.write(f'  • Allow Advance Salary Application: {settings.allow_advance_salary_application}')
            self.stdout.write(f'  • Allow Losses/Damage Submission: {settings.allow_losses_damage_submission}')
            self.stdout.write(f'  • Allow Expense Claims Application: {settings.allow_expense_claims_application}')
            self.stdout.write(f'  • Require Password Change on First Login: {settings.require_password_change_on_first_login}')
            self.stdout.write(f'  • Session Timeout: {settings.session_timeout_minutes} minutes')
            self.stdout.write(f'  • Allow Weekend Login: {settings.allow_weekend_login}')
            self.stdout.write(f'  • Max Failed Login Attempts: {settings.max_failed_login_attempts}')
            self.stdout.write(f'  • Account Lockout Duration: {settings.account_lockout_duration_minutes} minutes')
            
            # Show exempt roles
            exempt_roles = settings.exempt_roles.all()
            if exempt_roles.exists():
                self.stdout.write('\n  Exempt Roles:')
                for role in exempt_roles:
                    self.stdout.write(f'    - {role.name}')
            else:
                self.stdout.write('\n  No exempt roles configured')
            
            self.stdout.write('\n' + self.style.SUCCESS('✓ ESS Settings initialized successfully!'))
            
            # Enable all ESS features for better UX
            if not options['reset']:
                self.stdout.write('\n' + self.style.SUCCESS('Enabling all ESS features...'))
                settings.allow_payslip_view = True
                settings.allow_leave_application = True
                settings.allow_timesheet_application = True
                settings.allow_overtime_application = True
                settings.allow_advance_salary_application = True
                settings.allow_losses_damage_submission = True
                settings.allow_expense_claims_application = True
                settings.save()
                self.stdout.write(self.style.SUCCESS('✓ All ESS features enabled'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Error initializing ESS settings: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())
            
            # Check if migrations are needed
            self.stdout.write('\n' + self.style.WARNING('If you see a database error, run:'))
            self.stdout.write('  python manage.py makemigrations hrm')
            self.stdout.write('  python manage.py migrate hrm')
            self.stdout.write('  python manage.py setup_ess_settings')

