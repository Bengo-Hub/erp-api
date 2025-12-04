from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models import (
    Regions, Departments, BankInstitution, BankBranches, 
    Projects, ProjectCategory
)
from business.models import Bussiness, BusinessLocation
from authmanagement.models import CustomUser

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds core data including regions, departments, banks, and other core models'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting to seed core data...'))
        
        # Note: Business, BusinessLocation, AppSettings, Banner, ContractSetting are created by middleware
        # We only need to seed data that is NOT automatically created by middleware
        
        # Note: Admin user creation moved to seed_initial.py to avoid duplication
        self.stdout.write(self.style.SUCCESS('✓ Superuser handled by seed_initial command'))
        
        # Get existing business (created by middleware)
        business = Bussiness.objects.first()
        if not business:
            self.stdout.write(self.style.ERROR('No business found. Please ensure middleware has run first.'))
            return
        
        # Get existing business location (created by middleware)
        location = BusinessLocation.objects.filter(default=True, is_active=True).first()
        if not location:
            self.stdout.write(self.style.WARNING('No business location found. Creating default location...'))
            location = BusinessLocation.objects.create(
                city='Nairobi',
                county='Nairobi',
                state='KE',
                country='KE',
                zip_code='00100',
                postal_code='00100',
                website='codevertexitsolutions.com',
                default=True,
                is_active=True
            )
        
        # Create regions
        regions_data = [
            {'name': 'Nairobi', 'code': 'NBI'},
            {'name': 'Mombasa', 'code': 'MBS'},
            {'name': 'Kisumu', 'code': 'KSM'},
            {'name': 'Nakuru', 'code': 'NKR'},
            {'name': 'Eldoret', 'code': 'ELD'},
            {'name': 'Thika', 'code': 'THK'},
            {'name': 'Kakamega', 'code': 'KKM'},
            {'name': 'Nyeri', 'code': 'NYR'},
            {'name': 'Machakos', 'code': 'MCK'},
            {'name': 'Kisii', 'code': 'KSI'}
        ]
        
        for region_data in regions_data:
            region, created = Regions.objects.get_or_create(
                name=region_data['name'],
                defaults={'code': region_data['code']}
            )
            if created:
                self.stdout.write(f'Created region: {region.name}')
        
        # Create departments
        departments_data = [
            {'title': 'Finance', 'code': 'FIN'},
            {'title': 'Human Resources', 'code': 'HR'},
            {'title': 'Information Technology', 'code': 'IT'},
            {'title': 'Operations', 'code': 'OPS'},
            {'title': 'Marketing', 'code': 'MKT'},
            {'title': 'Sales', 'code': 'SAL'},
            {'title': 'Customer Service', 'code': 'CS'},
            {'title': 'Research & Development', 'code': 'RND'},
            {'title': 'Legal', 'code': 'LEG'},
            {'title': 'Administration', 'code': 'ADM'}
        ]
        
        for dept_data in departments_data:
            dept, created = Departments.objects.get_or_create(
                title=dept_data['title'],
                defaults={'code': dept_data['code']}
            )
            if created:
                self.stdout.write(f'Created department: {dept.title}')
        
        # Create banks
        banks_data = [
            'Equity Bank',
            'KCB Bank',
            'Cooperative Bank',
            'Standard Chartered Bank',
            'Absa Bank',
            'NCBA Bank',
            'Diamond Trust Bank',
            'I&M Bank',
            'Stanbic Bank',
            'Commercial Bank of Africa'
        ]

        # De-duplicate existing banks by name (keep oldest, remove others) to avoid MultipleObjectsReturned on get_or_create
        try:
            from django.db.models import Count
            dup_banks = BankInstitution.objects.values('name').annotate(c=Count('id')).filter(c__gt=1)
            for dup in dup_banks:
                same_named = BankInstitution.objects.filter(name=dup['name']).order_by('id')
                keeper = same_named.first()
                same_named.exclude(id=keeper.id).delete()
        except Exception:
            pass

        for bank_name in banks_data:
            # Create unique codes for banks
            code = bank_name[:3].upper()
            if code == 'STA':  # Handle Standard Chartered Bank
                code = 'SCB'
            elif code == 'COM':  # Handle Commercial Bank of Africa
                code = 'CBA'

            # Be tolerant of existing duplicates
            try:
                bank_institution, created = BankInstitution.objects.get_or_create(
                    name=bank_name,
                    defaults={
                        'code': code,
                        'short_code': code,
                        'swift_code': f"{code}KENA",
                        'country': 'Kenya',
                        'is_active': True
                    }
                )
            except Exception:
                bank_institution = BankInstitution.objects.filter(name=bank_name).order_by('id').first()
                created = False
            if created:
                self.stdout.write(f'Created bank institution: {bank_institution.name}')
        
        # Create bank branches for major banks
        major_banks = BankInstitution.objects.filter(name__in=['Equity Bank', 'KCB Bank', 'Cooperative Bank'])
        for bank in major_banks:
            for i in range(1, 4):  # Create 3 branches per major bank
                branch_name = f"{bank.name} Branch {i}"
                branch_code = f"{bank.name[:3].upper()}{i:02d}"
                
                branch, created = BankBranches.objects.get_or_create(
                    bank=bank,
                    name=branch_name,
                    defaults={
                        'code': branch_code,
                        'address': f"Nairobi CBD Branch {i}",
                        'phone': f"+25470000000{i}",
                        'email': f"branch{i}@{bank.name.lower().replace(' ', '')}.com",
                        'is_active': True
                    }
                )
                if created:
                    self.stdout.write(f'Created bank branch: {branch.name}')
        
        # Create project categories
        categories_data = [
            'Software Development',
            'Infrastructure',
            'Marketing Campaign',
            'Product Launch',
            'Process Improvement',
            'Training Program',
            'Research Project',
            'Client Implementation',
            'System Migration',
            'Quality Assurance'
        ]
        
        for cat_name in categories_data:
            category, created = ProjectCategory.objects.get_or_create(title=cat_name)
            if created:
                self.stdout.write(f'Created project category: {category.title}')
        
        # Create sample projects
        projects_data = [
            {
                'title': 'ERP System Implementation',
                'code': 'ERP001',
                'category': 'System Migration'
            },
            {
                'title': 'Digital Marketing Campaign',
                'code': 'MKT001',
                'category': 'Marketing Campaign'
            },
            {
                'title': 'Employee Training Program',
                'code': 'TRN001',
                'category': 'Training Program'
            }
        ]
        
        for project_data in projects_data:
            category = ProjectCategory.objects.filter(title=project_data['category']).order_by('id').first()
            project, created = Projects.objects.get_or_create(
                title=project_data['title'],
                defaults={
                    'code': project_data['code'],
                    'category': category
                }
            )
            if created:
                self.stdout.write(f'Created project: {project.title}')
        
        self.stdout.write(self.style.SUCCESS('Core data seeding completed successfully!'))
        self.stdout.write(self.style.SUCCESS('Note: AppSettings, Banner, ContractSetting are automatically created by middleware'))
