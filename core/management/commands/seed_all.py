from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import connection
from django.core.management.base import CommandError


class Command(BaseCommand):
    help = 'Seeds comprehensive DEMO data across all apps (for development/testing only - NOT for production)'

    def add_arguments(self, parser):
        # Default: CLEAR data before seeding. Use --no-clear to preserve data.
        parser.add_argument('--no-clear', action='store_true', help='Do NOT clear existing data before seeding (default: clear)')
        parser.add_argument('--simulate', action='store_true', help='Simulate manufacturing workflows where supported')
        parser.add_argument('--full', action='store_true', help='Run full manufacturing seeding (products + raw materials)')
        parser.add_argument('--products', type=int, default=20, help='Number of demo products to generate')
        parser.add_argument('--employees', type=int, default=1, help='Number of demo employees to generate')
        parser.add_argument('--minimal', action='store_true', help='Seed a minimal dataset (1-2 per model)')

    def handle(self, *args, **options):
        # Clear by default unless explicitly disabled
        clear_data = not options.get('no_clear')
        simulate = options.get('simulate')
        full = options.get('full')
        minimal = options.get('minimal')
        products_count = options.get('products')
        employees_count = options.get('employees')

        if minimal:
            # Strict minimal mode: seed only ONE item per dataset where applicable
            products_count = 1
            employees_count = 1

        self.stdout.write(self.style.WARNING('⚠️  DEMO DATA SEEDING - For Development/Testing Only'))
        self.stdout.write(self.style.WARNING('⚠️  NOT for production use! Use seed_initial for production.'))
        self.stdout.write(self.style.SUCCESS('\nStarting comprehensive demo data seeding...'))

        # Always clear existing user data before seeding to ensure consistent initial accounts
        self._clear_user_data()

        if clear_data:
            self.stdout.write(self.style.WARNING('Clearing existing seeded data...'))
            self._clear_seeded_data()

        # SEEDING ORDER (based on dependencies):
        # 1. Core data (regions, departments, banks, etc.) - no dependencies
        # 2. Business data (settings, tax rates, etc.) - depends on core
        # 3. Addresses data - depends on business
        # 4. HRM employees - depends on core, business, addresses
        # 5. HRM payroll formulas - depends on core, business (CRITICAL for payroll system)
        # 6. HRM leave data - depends on employees
        # 7. HRM appraisals data - depends on employees
        # 8. Ecommerce data - depends on business, core
        # 9. Manufacturing data - depends on ecommerce, business, core
        # 10. Finance data - depends on business, core
        # 11. CRM campaigns - depends on business, ecommerce
        # 12. Procurement data - depends on business, ecommerce, core

        try:
            # 1. Core data seeding
            self.stdout.write('1. Seeding core data (regions, departments, banks, etc.)...')
            call_command('seed_core_data')
        except Exception as e:
            if 'duplicate key value violates unique constraint' in str(e):
                self.stdout.write(self.style.WARNING(f'Core data already exists, continuing...'))
            else:
                self.stdout.write(self.style.ERROR(f'Core data seeding failed: {e}'))
                raise CommandError(f'Core data seeding failed: {e}')

        try:
            # 2. Business data seeding
            self.stdout.write('2. Seeding business data (settings, tax rates, etc.)...')
            call_command('seed_business_data')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Business data seeding failed: {e}'))
            raise CommandError(f'Business data seeding failed: {e}')

        try:
            # 3. Addresses data seeding
            self.stdout.write('3. Seeding addresses data (address books, etc.)...')
            call_command('seed_addresses_data')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Addresses data seeding failed: {e}'))
            raise CommandError(f'Addresses data seeding failed: {e}')

        try:
            # 4. CRM contacts seeding (critical for procurement, invoices, quotes)
            self.stdout.write('4. Seeding CRM contacts (customers and suppliers)...')
            if minimal:
                call_command('seed_contacts', count=1, minimal=True)
            else:
                call_command('seed_contacts', count=5)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'CRM contacts seeding failed: {e}'))

        try:
            # 5. HRM employees seeding
            self.stdout.write(f'5. Seeding HRM employees ({employees_count} employee{"s" if employees_count != 1 else ""})...')
            if minimal:
                call_command('seed_employees', count=employees_count, minimal=True)
            else:
                call_command('seed_employees', count=employees_count)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'HRM employees seeding failed: {e}'))

        try:
            # 6. HRM payroll formulas seeding (CRITICAL for payroll system)
            self.stdout.write('6. Seeding HRM payroll formulas...')
            call_command('seed_payroll_formulas')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'HRM payroll formulas seeding failed: {e}'))

        try:
            # 7. HRM leave data seeding
            self.stdout.write('7. Seeding HRM leave data...')
            if minimal:
                call_command('seed_leave_data', minimal=True)
            else:
                call_command('seed_leave_data')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'HRM leave data seeding failed: {e}'))

        try:
            # 8. HRM appraisals data seeding
            self.stdout.write('8. Seeding HRM appraisals data...')
            if minimal:
                call_command('seed_appraisal_data', minimal=True)
            else:
                call_command('seed_appraisal_data')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'HRM appraisals data seeding failed: {e}'))

        try:
            # 9. Ecommerce products seeding
            if minimal:
                self.stdout.write(f'9. Seeding ecommerce products ({products_count})...')
                call_command('seed_products', count=products_count, minimal=True)
            else:
                self.stdout.write(f'9. Seeding ecommerce products ({products_count} products)...')
                call_command('seed_products', count=products_count)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Ecommerce products seeding failed: {e}'))

        try:
            # 10. Manufacturing data seeding
            if minimal:
                self.stdout.write('10. Seeding minimal manufacturing data...')
                call_command('seed_manufacturing', full=full, simulate=simulate, minimal=True)
            else:
                self.stdout.write('10. Seeding manufacturing data...')
                call_command('seed_manufacturing', full=full, simulate=simulate)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Manufacturing data seeding failed: {e}'))

        try:
            # 11. Finance payment accounts seeding
            self.stdout.write('11. Seeding finance payment accounts...')
            if minimal:
                    call_command('seed_payment_accounts', count=1, minimal=True)
            else:
                call_command('seed_payment_accounts')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Finance payment accounts seeding failed: {e}'))

        try:
            # 12. Finance bank statements seeding
            self.stdout.write('12. Seeding finance bank statements...')
            if minimal:
                    call_command('seed_bank_statements', count=1, minimal=True)
            else:
                call_command('seed_bank_statements')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Finance bank statements seeding failed: {e}'))

        try:
            # 13. CRM campaigns seeding
            self.stdout.write('13. Seeding CRM campaigns data...')
            if minimal:
                call_command('seed_campaigns', minimal=True)
            else:
                call_command('seed_campaigns')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'CRM campaigns seeding failed: {e}'))

        try:
            # 14. Procurement data seeding
            self.stdout.write('14. Seeding procurement data...')
            if minimal:
                call_command('seed_procurement_data', minimal=True)
            else:
                call_command('seed_procurement_data')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Procurement data seeding failed: {e}'))

        # 15. Assets seeding (depends on business & branches)
        try:
            self.stdout.write('15. Seeding assets data...')
            if minimal:
                    call_command('seed_assets', users=1, categories=1, assets=1, minimal=True)
            else:
                call_command('seed_assets')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Assets data seeding failed: {e}'))

        try:
            # 16. Notifications setup
            self.stdout.write('16. Setting up notifications...')
            call_command('setup_notifications')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Notifications setup failed: {e}'))

        self.stdout.write(self.style.SUCCESS('Comprehensive seeding completed successfully!'))
        self.stdout.write(self.style.SUCCESS('Note: Business, business location, and branding settings are created by the seed scripts (see seed_business_data)'))

        # Ensure centralized RBAC provisioning is applied per roles defined in core.security
        try:
            from core.security import ensure_rbac_provisioned
            self.stdout.write('Applying centralized RBAC provisioning (core.security)...')
            ensure_rbac_provisioned()
            self.stdout.write(self.style.SUCCESS('RBAC provisioning completed.'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'RBAC provisioning failed: {e}'))

    def _clear_seeded_data(self):
        """Clear existing seeded data while preserving system-critical data"""
        with connection.cursor() as cursor:
            # Clear user-related data FIRST to avoid FK constraints and ensure fresh user state
            self.stdout.write('  Clearing user data...')
            try:
                cursor.execute("DELETE FROM authmanagement_userpreferences")
            except Exception as e:
                self.stdout.write(f'    Warning: User preferences table may not exist: {e}')
            try:
                cursor.execute("DELETE FROM authmanagement_userlog")
            except Exception as e:
                self.stdout.write(f'    Warning: User log table may not exist: {e}')
            # Clear M2M relations (names are Django defaults; may be present even with custom user)
            try:
                cursor.execute("DELETE FROM auth_user_groups")
            except Exception as e:
                self.stdout.write(f'    Warning: auth_user_groups table may not exist: {e}')
            try:
                cursor.execute("DELETE FROM auth_user_user_permissions")
            except Exception as e:
                self.stdout.write(f'    Warning: auth_user_user_permissions table may not exist: {e}')
            # Finally clear users (middleware/seed will recreate admin/demo as needed)
            try:
                cursor.execute("DELETE FROM authmanagement_customuser")
            except Exception as e:
                self.stdout.write(f'    Warning: CustomUser table may not exist: {e}')

            # Clear core data FIRST (since other data depends on it)
            self.stdout.write('  Clearing core data...')
            try:
                cursor.execute("DELETE FROM core_projects")
                cursor.execute("DELETE FROM core_projectcategory")
                cursor.execute("DELETE FROM core_bankbranches")
                cursor.execute("DELETE FROM core_bankinstitution")
                cursor.execute("DELETE FROM core_departments")
                cursor.execute("DELETE FROM core_regions")
            except Exception as e:
                self.stdout.write(f'    Warning: Some core tables may not exist: {e}')
            
            # Clear seeded data in reverse dependency order
            self.stdout.write('  Clearing manufacturing data...')
            try:
                cursor.execute("DELETE FROM manufacturing_qualitycheck")
                cursor.execute("DELETE FROM manufacturing_batchrawmaterial")
                cursor.execute("DELETE FROM manufacturing_productionbatch")
                cursor.execute("DELETE FROM manufacturing_formulaingredient")
                cursor.execute("DELETE FROM manufacturing_productformula")
                cursor.execute("DELETE FROM manufacturing_rawmaterialusage")
                cursor.execute("DELETE FROM manufacturing_manufacturinganalytics")
            except Exception as e:
                self.stdout.write(f'    Warning: Some manufacturing tables may not exist: {e}')
            
            self.stdout.write('  Clearing ecommerce data...')
            try:
                cursor.execute("DELETE FROM ecommerce_product_products")
                cursor.execute("DELETE FROM ecommerce_product_category")
                cursor.execute("DELETE FROM ecommerce_product_productbrands")
                cursor.execute("DELETE FROM ecommerce_stockinventory_stockinventory")
                cursor.execute("DELETE FROM ecommerce_stockinventory_unit")
            except Exception as e:
                self.stdout.write(f'    Warning: Some ecommerce tables may not exist: {e}')
            
            self.stdout.write('  Clearing HRM data...')
            try:
                cursor.execute("DELETE FROM hrm_appraisals_appraisalresponse")
                cursor.execute("DELETE FROM hrm_appraisals_appraisalquestion")
                cursor.execute("DELETE FROM hrm_appraisals_appraisaltemplate")
                cursor.execute("DELETE FROM hrm_appraisals_appraisalcycle")
                cursor.execute("DELETE FROM hrm_leave_leaveapplication")
                cursor.execute("DELETE FROM hrm_leave_leavetype")
                cursor.execute("DELETE FROM hrm_employees_contract")
                cursor.execute("DELETE FROM hrm_employees_hrdetails")
                cursor.execute("DELETE FROM hrm_employees_salarydetails")
                cursor.execute("DELETE FROM hrm_employees_contactdetails")
                cursor.execute("DELETE FROM hrm_employees_nextofkin")
                cursor.execute("DELETE FROM hrm_employees_employeebankaccount")
                cursor.execute("DELETE FROM hrm_employees_employee")
            except Exception as e:
                self.stdout.write(f'    Warning: Some HRM tables may not exist: {e}')
            
            self.stdout.write('  Clearing addresses data...')
            try:
                cursor.execute("DELETE FROM addresses_addressbook")
            except Exception as e:
                self.stdout.write(f'    Warning: Addresses table may not exist: {e}')
            
            self.stdout.write('  Clearing business settings...')
            try:
                cursor.execute("DELETE FROM business_taxrates")
                cursor.execute("DELETE FROM business_productsettings")
                cursor.execute("DELETE FROM business_salesettings")
                cursor.execute("DELETE FROM business_prefixsettings")
                cursor.execute("DELETE FROM business_servicetypes")
            except Exception as e:
                self.stdout.write(f'    Warning: Some business tables may not exist: {e}')
            
            self.stdout.write('  Clearing finance data...')
            try:
                cursor.execute("DELETE FROM finance_reconciliation_bankstatementline")
                cursor.execute("DELETE FROM finance_accounts_paymentaccounts")
                # Clear payment/billing tables so seeds start fresh
                cursor.execute("DELETE FROM finance_payments")
                cursor.execute("DELETE FROM payment_paymenttransaction")
                cursor.execute("DELETE FROM payment_paymentmethod")
                cursor.execute("DELETE FROM payment_billingitem")
                cursor.execute("DELETE FROM payment_billingdocumenthistory")
                cursor.execute("DELETE FROM payment_billingdocument")
            except Exception as e:
                self.stdout.write(f'    Warning: Some finance tables may not exist: {e}')
            
            self.stdout.write('  Clearing procurement data...')
            try:
                cursor.execute("DELETE FROM procurement_purchases_purchaseorderitem")
                cursor.execute("DELETE FROM procurement_purchases_purchaseorder")
                cursor.execute("DELETE FROM procurement_requisitions_requisitionitem")
                cursor.execute("DELETE FROM procurement_requisitions_requisition")
                cursor.execute("DELETE FROM procurement_contracts_contract")
            except Exception as e:
                self.stdout.write(f'    Warning: Some procurement tables may not exist: {e}')
            
            # Reset auto-increment counters (only for tables that exist)
            self.stdout.write('  Resetting auto-increment counters...')
            try:
                # PostgreSQL uses sequences instead of AUTO_INCREMENT
                # For CustomUser, set to max(id) + 1 since it's not cleared
                cursor.execute("SELECT setval('authmanagement_customuser_id_seq', (SELECT COALESCE(MAX(id), 0) + 1 FROM authmanagement_customuser), false)")
                cursor.execute("SELECT setval('manufacturing_qualitycheck_id_seq', 1, false)")
                cursor.execute("SELECT setval('manufacturing_batchrawmaterial_id_seq', 1, false)")
                cursor.execute("SELECT setval('manufacturing_productionbatch_id_seq', 1, false)")
                cursor.execute("SELECT setval('manufacturing_productformula_id_seq', 1, false)")
                cursor.execute("SELECT setval('ecommerce_product_products_id_seq', 1, false)")
                cursor.execute("SELECT setval('ecommerce_product_category_id_seq', 1, false)")
                cursor.execute("SELECT setval('hrm_employees_employee_id_seq', 1, false)")
                cursor.execute("SELECT setval('hrm_employees_employeebankaccount_id_seq', 1, false)")
                cursor.execute("SELECT setval('core_projects_id_seq', 1, false)")
                cursor.execute("SELECT setval('core_bankinstitution_id_seq', 1, false)")
                cursor.execute("SELECT setval('core_bankbranches_id_seq', 1, false)")
                cursor.execute("SELECT setval('finance_reconciliation_bankstatementline_id_seq', 1, false)")
                cursor.execute("SELECT setval('finance_accounts_paymentaccounts_id_seq', 1, false)")
                cursor.execute("SELECT setval('procurement_purchases_purchaseorder_id_seq', 1, false)")
                cursor.execute("SELECT setval('procurement_requisitions_requisition_id_seq', 1, false)")
                cursor.execute("SELECT setval('procurement_contracts_contract_id_seq', 1, false)")
            except Exception as e:
                self.stdout.write(f'    Warning: Some sequence resets may have failed: {e}')
            
            self.stdout.write('  Data clearing completed')


    def _clear_user_data(self):
        """Always clear existing user data before seeding"""
        with connection.cursor() as cursor:
            self.stdout.write('  (pre-seed) Clearing user data...')
            try:
                # Clear custom user M2M relations first (for custom user model)
                cursor.execute("DELETE FROM authmanagement_customuser_groups")
            except Exception as e:
                self.stdout.write(f'    Warning: authmanagement_customuser_groups table may not exist: {e}')
            try:
                cursor.execute("DELETE FROM authmanagement_customuser_user_permissions")
            except Exception as e:
                self.stdout.write(f'    Warning: authmanagement_customuser_user_permissions table may not exist: {e}')
            try:
                cursor.execute("DELETE FROM authmanagement_userpreferences")
            except Exception as e:
                self.stdout.write(f'    Warning: User preferences table may not exist: {e}')
            try:
                cursor.execute("DELETE FROM authmanagement_userlog")
            except Exception as e:
                self.stdout.write(f'    Warning: User log table may not exist: {e}')
            try:
                cursor.execute("DELETE FROM auth_user_groups")
            except Exception as e:
                self.stdout.write(f'    Warning: auth_user_groups table may not exist: {e}')
            try:
                cursor.execute("DELETE FROM auth_user_user_permissions")
            except Exception as e:
                self.stdout.write(f'    Warning: auth_user_user_permissions table may not exist: {e}')
            try:
                cursor.execute("DELETE FROM authmanagement_customuser")
            except Exception as e:
                self.stdout.write(f'    Warning: CustomUser table may not exist: {e}')
                # If can't delete, don't reset sequence to 1
                return
            try:
                cursor.execute("SELECT setval('authmanagement_customuser_id_seq', 1, false)")
            except Exception as e:
                self.stdout.write(f'    Warning: Could not reset user id sequence: {e}')
