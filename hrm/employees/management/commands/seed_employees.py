# commands/seed_employees.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils.timezone import make_aware
from datetime import datetime, timedelta
import random
from faker import Faker

from authmanagement.models import CustomUser
from business.models import Bussiness, BusinessLocation, Branch
from core.models import *
from hrm.employees.models import *
from django.contrib.auth.models import Group 

fake = Faker()

class Command(BaseCommand):
    help = 'Seed database with demo employee records linked to Codevertex Africa business'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=1, help='Number of employees to generate')

    def handle(self, *args, **options):
        count = options.get('count', 1)
        self.stdout.write(self.style.SUCCESS(f'Starting to seed {count} demo employees across multiple branches...'))
    
        # Get the business "Codevertex IT Solutions" (standardized), fallback to first
        business = Bussiness.objects.filter(name__iexact='Codevertex IT Solutions').first() or Bussiness.objects.first()
        if not business:
            self.stdout.write(self.style.ERROR('No business found. Please run business seeding first.'))
            return
        
        # Get all branches for distribution
        branches = list(Branch.objects.filter(business=business, is_active=True))
        if not branches:
            self.stdout.write(self.style.ERROR('No branches found. Please run business seeding first.'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'Found {len(branches)} branches for employee distribution'))
        
        # Get all regions for distribution
        regions = list(Regions.objects.all())
        if not regions:
            self.stdout.write(self.style.ERROR('No regions found. Please run core data seeding first.'))
            return

        # Create employees distributed across branches
        for i in range(1, count + 1):
            try:
                # Distribute employees across branches
                branch = branches[i % len(branches)]
                # Try to match region with branch location, fallback to any region
                region = self._get_region_for_branch(branch, regions)
                
                self.create_demo_employee(i, business, branch, region)
                self.stdout.write(self.style.SUCCESS(f'Successfully created demo employee #{i} in {branch.name}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error creating employee #{i}: {str(e)}'))

        self.stdout.write(self.style.SUCCESS(f'Successfully seeded {count} demo employees across {len(branches)} branches!'))
    
    def _get_region_for_branch(self, branch, regions):
        """Match region to branch location or return random region"""
        # Try to find a region matching the branch city
        for region in regions:
            if branch.location.city.lower() in region.name.lower() or region.name.lower() in branch.location.city.lower():
                return region
        # Fallback to random region
        return random.choice(regions)

    def create_demo_employee(self, index, business, branch, region):
        # Create user
        first_name = fake.first_name()
        last_name = fake.last_name()
        email = f"{first_name.lower()}.{last_name.lower()}@codevertexafrica.com"
        
        user, created = CustomUser.objects.get_or_create(
            email=email,
            defaults={
                "first_name": first_name,
                "middle_name": fake.first_name(),
                "last_name": last_name,
                "is_staff": True,
                "is_active": True
            }
        )
        if created:
            user.set_password("Demo@123")
            user.save()
        
        # Add to staff group
        group, _ = Group.objects.get_or_create(name="staff")
        user.groups.add(group)
        user.save()

        # Create employee linked to the business
        employee, _ = Employee.objects.get_or_create(
            user=user,
            organisation=business,
            defaults={
                "gender": random.choice(['Male', 'Female', 'Other']),
                "date_of_birth": fake.date_of_birth(minimum_age=22, maximum_age=55),
                "residential_status": random.choice(['Resident', 'Non-Resident']),
                "national_id": f"{random.randint(10000000, 99999999)}",
                "pin_no": f"A{random.randint(100000000, 999999999)}Z",
                "shif_or_nhif_number": f"NHIF{random.randint(100000, 999999)}",
                "nssf_no": f"NSSF{random.randint(100000, 999999)}",
            }
        )

        # Get existing bank institution (don't create new ones)
        bank_names = ['Equity Bank', 'KCB Bank', 'Cooperative Bank', 'Standard Chartered Bank', 'Absa Bank']
        bank_name = random.choice(bank_names)
        bank_institution = BankInstitution.objects.filter(name=bank_name).first()
        
        if not bank_institution:
            # Fallback to any existing bank if the preferred one doesn't exist
            bank_institution = BankInstitution.objects.first()
            if not bank_institution:
                self.stdout.write(self.style.ERROR(f'No bank institutions found. Please run core data seeding first.'))
                return
        
        # Get or create a specific bank branch for this employee
        branch_name = f"{bank_institution.name} Nairobi Branch {random.randint(1, 5)}"
        bank_branch, _ = BankBranches.objects.get_or_create(
            bank=bank_institution,
            name=branch_name,
            defaults={
                "code": str(random.randint(10, 99)),
                "address": "Nairobi CBD",
                "phone": f"+254{random.randint(100000000, 999999999)}",
                "email": f"nairobi@{bank_institution.name.lower().replace(' ', '')}.com",
                "is_active": True
            }
        )

        # Salary details
        basic_salary = random.randint(30000, 200000)
        employment_type = random.choice(['regular-fixed', 'regular-open', 'intern', 'probationary', 'casual'])
        
        # Create employee bank account with unique account number
        account_number = f"{random.randint(1000000000, 9999999999)}"
        # Ensure account number is unique
        while EmployeeBankAccount.objects.filter(account_number=account_number).exists():
            account_number = f"{random.randint(1000000000, 9999999999)}"
        
        employee_bank_account, _ = EmployeeBankAccount.objects.get_or_create(
            employee=employee,
            bank_institution=bank_institution,
            account_number=account_number,
            defaults={
                'bank_branch': bank_branch,
                'account_name': f"{first_name} {last_name}",
                'account_type': 'savings',
                'is_primary': True,
                'status': 'active',
                'is_verified': True,
                'opened_date': fake.date_between(start_date='-2y', end_date='-6m')
            }
        )

        salary_details, _ = SalaryDetails.objects.get_or_create(
            employee=employee,
            defaults={
                'employment_type': employment_type,
                'monthly_salary': basic_salary,
                'pay_type': "gross",
                'work_hours': 8,
                'hourly_rate': None,
                'daily_rate': None,
                'income_tax': "primary",
                'deduct_shif_or_nhif': True,
                'deduct_nssf': True,
                'tax_excemption_amount': None,
                'payment_type': "bank",
                'bank_account': employee_bank_account,
                'mobile_number': f"+2547{random.randint(10000000, 99999999)}"
            }
        )

        # HR Details - linked to Nairobi
        dept_title = random.choice(['Finance', 'HR', 'IT', 'Operations', 'Marketing'])
        department, _ = Departments.objects.get_or_create(
            title=dept_title,
            defaults={
                "code": f"DEPT{index}",
            }
        )
        
        job_title = random.choice(['Manager', 'Officer', 'Assistant', 'Director', 'Analyst'])
        job_title_obj, _ = JobTitle.objects.get_or_create(title=f"{job_title} ({dept_title})")

        # Create active contract based on current date
        emp_date = fake.date_between(start_date='-2y', end_date='-6m')  # Employment started 6 months to 2 years ago
        end_date = emp_date + timedelta(days=random.randint(365, 1095))  # 1 to 3 years contract
        
        # Ensure contract is active (end date in future)
        if end_date < datetime.now().date():
            end_date = datetime.now().date() + timedelta(days=random.randint(180, 365))  # Extend to future
        
        hr_details, _ = HRDetails.objects.get_or_create(
            employee=employee,
            defaults={
                'job_or_staff_number': f"EMP{random.randint(1000, 9999)}",
                'job_title': job_title_obj,
                'department': department,
                'head_of': None,
                'reports_to': None,
                'region': region,  # Distributed across regions
                'branch': branch,  # Link to assigned branch
                'project': None,
                'date_of_employment': emp_date,
                'board_director': False
            }
        )

        # Contract - ensure active status
        duration = round((end_date - emp_date).days / 365, 1)  # in years
        contract_status = 'active' if end_date > datetime.now().date() else 'expired'
        
        contract, _ = Contract.objects.get_or_create(
            employee=employee,
            defaults={
                'status': contract_status,
                'contract_start_date': emp_date,
                'contract_end_date': end_date,
                'salary': basic_salary,
                'pay_type': "gross",
                'contract_duration': duration,
            }
        )

        # Contact details - match branch location
        contact_details, _ = ContactDetails.objects.get_or_create(
            employee=employee,
            defaults={
                'personal_email': f"personal.{email}",
                'country': 'KE',
                'county': branch.location.county,
                'city': branch.location.city,
                'zip': branch.location.zip_code or '00100',
                'address': fake.address(),
                'mobile_phone': f"+2547{random.randint(10000000, 99999999)}",
                'official_phone': f"+2547{random.randint(10000000, 99999999)}",
            }
        )

        # Next of kin
        next_of_kin, _ = NextOfKin.objects.get_or_create(
            employee=employee,
            defaults={
                'name': f"{fake.first_name()} {fake.last_name()}",
                'relation': random.choice(['Spouse', 'Parent', 'Sibling', 'Child']),
                'phone': f"+2547{random.randint(10000000, 99999999)}",
                'email': f"kin.{first_name.lower()}.{last_name.lower()}@codevertexafrica.com",
            }
        )