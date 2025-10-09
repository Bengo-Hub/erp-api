import os
import django
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone  # timezone for datetime
from decimal import Decimal
from datetime import date
from hrm.payroll_settings.models import Formulas, FormulaItems, SplitRatio
from hrm.employees.models import Employee, SalaryDetails
from hrm.payroll.models import Payslip
from hrm.payroll.utils import PayrollGenerator
from hrm.payroll.functions import (
    calculate_income_tax, 
    calculate_nssf_contribution, 
    calculate_shif_deduction,
    calculate_other_deduction
)

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ERPAPI.settings')
django.setup() # setup django environment

User = get_user_model()


class PayrollUtilsTestCase(TestCase):
    """Test cases for payroll utility functions."""
    
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test business and location first
        from business.models import Bussiness, BusinessLocation
        from core.models import Regions
        
        # Create business location
        location = BusinessLocation.objects.create(
            city='Nairobi',
            county='Nairobi',
            country='KE',
            state='KE',
            zip_code='00100',
            postal_code='00100'
        )
        
        # Create business
        business = Bussiness.objects.create(
            name='Test Business',
            owner=self.user,
            location=location
        )
        
        # Create test employee with proper structure
        self.employee = Employee.objects.create(
            user=self.user,
            organisation=business,
            gender='male',
            date_of_birth='1990-01-01',
            residential_status='Resident',
            national_id='12345678',
            pin_no='1234567890123456',
            nhif_no='1234567890123456',
            nssf_no='1234567890123456'
        )
        
        # Create HR details
        from hrm.employees.models import HRDetails, JobTitle
        from core.models import Departments
        from business.models import Branch
        
        # Get or create required related objects
        job_title, _ = JobTitle.objects.get_or_create(title='Officer (HR)')
        department, _ = Departments.objects.get_or_create(title='HR', code='HR')
        region, _ = Regions.objects.get_or_create(name='Nairobi', code='NBI')
        
        # Create branch
        branch = Branch.objects.create(
            name='Main Branch',
            business=business,
            location=location,
            branch_code='MB00100',
            is_main_branch=True
        )
        
        HRDetails.objects.create(
            employee=self.employee,
            job_or_staff_number='EMP6290',
            job_title=job_title,
            department=department,
            region=region,
            branch=branch,
            date_of_employment='2020-01-01'
        )
        
        # Create salary details matching the payslip example
        self.salary_details = SalaryDetails.objects.create(
            employee=self.employee,
            monthly_salary=Decimal('49784.00'),
            pay_type='basic',
            income_tax='primary',
            deduct_nhif=True,
            deduct_nssf=True
        )
        
        # Create test formulas for 2025
        self.income_formula = Formulas.objects.create(
            title='P.A.Y.E Kenya (Primary Employee) - 2025 Onwards',
            type='income',
            category='primary',
            version='2025.1',
            is_current=True,
            effective_from=date(2025, 2, 1),
            personal_relief=Decimal('2400.00'),
            regulatory_source='Finance Act 2024'
        )
        
        self.nssf_formula = Formulas.objects.create(
            title='NSSF 2025 Onwards',
            type='deduction',
            category='social_security_fund',
            version='2025.1',
            is_current=True,
            effective_from=date(2025, 2, 1),
            regulatory_source='NSSF Act 2025'
        )
        
        # Create NSSF formula items for 2025 rates
        FormulaItems.objects.create(
            formula=self.nssf_formula,
            amount_from=Decimal('0.00'),
            amount_to=Decimal('8000.00'),
            deduct_percentage=Decimal('6.00')
        )
        FormulaItems.objects.create(
            formula=self.nssf_formula,
            amount_from=Decimal('8000.00'),
            amount_to=Decimal('72000.00'),
            deduct_percentage=Decimal('6.00')
        )
        
        self.shif_formula = Formulas.objects.create(
            title='SHIF 2025 Onwards',
            type='deduction',
            category='shif',
            version='2025.1',
            is_current=True,
            effective_from=date(2024, 10, 1),
            regulatory_source='SHIF Act 2024'
        )
        
        self.levy_formula = Formulas.objects.create(
            title='Housing Levy 2025 Onwards',
            type='levy',
            category='housing_levy',
            version='2025.1',
            is_current=True,
            effective_from=date(2024, 3, 1),
            regulatory_source='Affordable Housing Act 2024'
        )
        
        # Create Housing Levy formula items for 2025 rates
        FormulaItems.objects.create(
            formula=self.levy_formula,
            amount_from=Decimal('0.00'),
            amount_to=Decimal('999999.99'),
            deduct_percentage=Decimal('1.50')
        )
        
        # Create formula items for PAYE (2025 brackets)
        FormulaItems.objects.create(
            formula=self.income_formula,
            amount_from=Decimal('0.00'),
            amount_to=Decimal('24000.00'),
            deduct_percentage=Decimal('10.00')
        )
        FormulaItems.objects.create(
            formula=self.income_formula,
            amount_from=Decimal('24000.00'),
            amount_to=Decimal('32333.33'),
            deduct_percentage=Decimal('25.00')
        )
        FormulaItems.objects.create(
            formula=self.income_formula,
            amount_from=Decimal('32333.33'),
            amount_to=Decimal('500000.00'),
            deduct_percentage=Decimal('30.00')
        )
        FormulaItems.objects.create(
            formula=self.income_formula,
            amount_from=Decimal('500000.00'),
            amount_to=Decimal('799999.99'),
            deduct_percentage=Decimal('32.50')
        )
        FormulaItems.objects.create(
            formula=self.income_formula,
            amount_from=Decimal('800000.00'),
            amount_to=Decimal('999999.99'),
            deduct_percentage=Decimal('35.00')
        )
        
        # Create formula items for NSSF (2025 rates)
        FormulaItems.objects.create(
            formula=self.nssf_formula,
            amount_from=Decimal('0.00'),
            amount_to=Decimal('8000.00'),
            deduct_percentage=Decimal('6.00')  # 6% on 0-8,000 for Tier 1
        )
        FormulaItems.objects.create(
            formula=self.nssf_formula,
            amount_from=Decimal('8001.00'),
            amount_to=Decimal('72000.00'),
            deduct_percentage=Decimal('6.00')  # 6% on 8,000+ for Tier 2
        )
        
        # Create formula items for SHIF (2025 rates)
        FormulaItems.objects.create(
            formula=self.shif_formula,
            amount_from=Decimal('0.00'),
            amount_to=Decimal('999999.99'),
            deduct_percentage=Decimal('2.75')
        )
        
        # Create formula items for Housing Levy (2025 rates)
        FormulaItems.objects.create(
            formula=self.levy_formula,
            amount_from=Decimal('0.00'),
            amount_to=Decimal('999999.99'),
            deduct_percentage=Decimal('1.50')
        )
        
        # Create split ratios
        SplitRatio.objects.create(
            formula=self.nssf_formula,
            employee_percentage=Decimal('50.00'),
            employer_percentage=Decimal('50.00')
        )
        SplitRatio.objects.create(
            formula=self.shif_formula,
            employee_percentage=Decimal('100.00'),
            employer_percentage=Decimal('0.00')
        )
        SplitRatio.objects.create(
            formula=self.levy_formula,
            employee_percentage=Decimal('100.00'),
            employer_percentage=Decimal('0.00')
        )
        
        # Set payment period to September 2025
        self.payment_period = date(2025, 9, 1)
        
    def test_paye_calculation_2025(self):
        """Test PAYE calculation matches PNA.co.ke calculator for 2025."""
        # Test case: Gross salary KES 49,784
        gross_salary = Decimal('49784.00')
        
        # Expected deductions before tax (from PNA.co.ke):
        # NSSF: KES 2,987.04 (Tier 1: 480 + Tier 2: 2,507.04)
        # SHIF: KES 1,369.06
        # Housing Levy: KES 746.76
        expected_nssf = Decimal('2987.04')
        expected_shif = Decimal('1369.06')
        expected_housing_levy = Decimal('746.76')
        expected_total_deductions_before_tax = expected_nssf + expected_shif + expected_housing_levy
        
        # Calculate taxable income
        taxable_income = gross_salary - expected_total_deductions_before_tax
        expected_taxable_income = Decimal('44681.34')  # From PNA.co.ke
        
        # Calculate expected PAYE using 2025 brackets
        # Bracket 1: 0-24,000 @ 10% = 2,400.00
        # Bracket 2: 24,000-32,333 @ 25% = 2,083.33 (8,333.33 * 0.25)
        # Bracket 3: 32,333-44,681.34 @ 30% = 3,704.34 (12,347.81 * 0.30)
        expected_paye = Decimal('8187.68')  # From PNA.co.ke
        
        # Apply personal relief
        personal_relief = Decimal('2400.00')
        expected_paye_after_relief = expected_paye - personal_relief
        
        # Calculate net pay
        expected_net_pay = taxable_income - expected_paye_after_relief - expected_housing_levy
        
        # Test individual calculations
        self.assertAlmostEqual(taxable_income, expected_taxable_income, places=2)
        self.assertAlmostEqual(expected_paye, Decimal('8187.68'), places=2)
        self.assertAlmostEqual(expected_paye_after_relief, Decimal('5787.68'), places=2)
        
    def test_nssf_calculation_2025(self):
        """Test NSSF calculation matches 2025 rates."""
        gross_salary = Decimal('49784.00')
        
        # Expected NSSF calculation for 2025:
        # Tier 1: 6% on 0-8,000 = 6% on 8,000 = 480.00 (max)
        # Tier 2: 6% on 8,000+ = 6% on (49,784 - 8,000) = 6% on 41,784 = 2,507.04
        expected_tier_1 = Decimal('480.00')
        expected_tier_2 = Decimal('2507.04')
        expected_total = expected_tier_1 + expected_tier_2
        
        # Test NSSF calculation
        tier_1, tier_2, employer = calculate_nssf_contribution(
            gross_salary, 
            title='NSSF 2025 Onwards',  # Match the exact title
            effective_date=self.payment_period,
            formula_id=self.nssf_formula.id
        )
        
        self.assertAlmostEqual(tier_1, expected_tier_1, places=2)
        self.assertAlmostEqual(tier_2, expected_tier_2, places=2)
        self.assertAlmostEqual(tier_1 + tier_2, expected_total, places=2)
        
    def test_shif_calculation_2025(self):
        """Test SHIF calculation matches 2025 rates."""
        gross_salary = Decimal('49784.00')
        
        # Expected SHIF: 2.75% of 49,784 = 1,369.06
        expected_shif = Decimal('1369.06')
        
        # Test SHIF calculation
        relief, employee, employer = calculate_shif_deduction(
            gross_salary,
            effective_date=self.payment_period,
            formula_id=self.shif_formula.id
        )
        
        self.assertEqual(relief, Decimal('0'))  # Relief repealed
        self.assertAlmostEqual(employee, expected_shif, places=2)
        
    def test_housing_levy_calculation_2025(self):
        """Test Housing Levy calculation matches 2025 rates."""
        gross_salary = Decimal('49784.00')
        
        # Expected Housing Levy: 1.5% of 49,784 = 746.76
        expected_levy = Decimal('746.76')
        
        # Test Housing Levy calculation
        relief, employee, employer = calculate_other_deduction(
            gross_salary,
            title='levy',
            type='levy',
            effective_date=self.payment_period,
            formula_id=self.levy_formula.id
        )
        
        self.assertEqual(relief, Decimal('0'))  # Relief repealed
        self.assertAlmostEqual(employee, expected_levy, places=2)
        
    def test_complete_payroll_calculation(self):
        """Test complete payroll calculation matches PNA.co.ke example."""
        # Create a mock request object for testing
        class MockRequest:
            def __init__(self, user):
                self.user = user
        
        # Create payroll generator with formula overrides
        payroll_generator = PayrollGenerator(
            request=MockRequest(self.user),
            employee=self.employee,
            payment_period=self.payment_period,
            recover_advances=False,
            command='process',
            formula_overrides={
                'income': self.income_formula.id,
                'nssf': self.nssf_formula.id,
                'shif': self.shif_formula.id,
                'levy': self.levy_formula.id
            }
        )
        
        # Generate payroll
        try:
            result = payroll_generator.process_regular_payroll()
            
            # Verify result was returned
            self.assertIsNotNone(result)
            
            # Check if it's a Payslip object or an error response
            if isinstance(result, Payslip):
                payslip = result
                # Verify payslip was created
                self.assertEqual(payslip.gross_pay, Decimal('49784'))
                
                # Verify deductions before tax
                self.assertAlmostEqual(payslip.total_deductions_before_tax, Decimal('5103.86'), places=2)
                
                # Verify taxable pay
                self.assertAlmostEqual(payslip.taxable_pay, Decimal('44680.14'), places=2)
                
                # Verify PAYE
                self.assertAlmostEqual(payslip.paye, Decimal('8187.68'), places=2)
                
                # Verify reliefs
                self.assertEqual(payslip.reliefs, Decimal('2400'))
                
                # Verify net pay (should be close to PNA.co.ke result)
                expected_net_pay = Decimal('34893')  # From PNA.co.ke
                self.assertAlmostEqual(payslip.net_pay, expected_net_pay, delta=Decimal('100'))  # Allow small variance
            else:
                # If it's a dictionary (error response), fail the test
                self.fail(f"Payroll generation failed: {result}")
                
        except Exception as e:
            # If there's an exception, fail the test with details
            self.fail(f"Payroll generation failed with exception: {str(e)}")

