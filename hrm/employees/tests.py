from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from datetime import date, datetime
from unittest.mock import patch, MagicMock

from hrm.employees.models import Employee, SalaryDetails, HRDetails
from hrm.payroll_settings.models import PayrollComponents
from hrm.payroll.models import Payslip

User = get_user_model()


class EmployeeTestCase(TestCase):
    """Test cases for employee management."""
    
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        # Create test employee
        self.employee = Employee.objects.create(
            user=self.user,
            employment_type='permanent',
            date_employed=date(2023, 1, 1),
            is_active=True
        )
        
        # Create HR details
        self.hr_details = HRDetails.objects.create(
            employee=self.employee,
            job_or_staff_number='EMP001',
            department='IT',
            position='Developer',
            is_active=True
        )
        
        # Create salary details
        self.salary_details = SalaryDetails.objects.create(
            employee=self.employee,
            basic_salary=Decimal('50000.00'),
            daily_rate=Decimal('2000.00'),
            hourly_rate=Decimal('250.00'),
            overtime_rate=Decimal('375.00'),
            is_active=True
        )

    def test_employee_creation(self):
        """Test employee creation with all required fields."""
        employee = Employee.objects.create(
            user=self.user,
            employment_type='contract',
            date_employed=date(2024, 1, 1)
        )
        
        self.assertEqual(employee.employment_type, 'contract')
        self.assertEqual(employee.date_employed, date(2024, 1, 1))
        self.assertTrue(employee.is_active)

    def test_employee_str_representation(self):
        """Test employee string representation."""
        expected_str = f"{self.employee.user.first_name} {self.employee.user.last_name}"
        self.assertEqual(str(self.employee), expected_str)

    def test_hr_details_creation(self):
        """Test HR details creation."""
        hr_details = HRDetails.objects.create(
            employee=self.employee,
            job_or_staff_number='EMP002',
            department='Finance',
            position='Accountant'
        )
        
        self.assertEqual(hr_details.job_or_staff_number, 'EMP002')
        self.assertEqual(hr_details.department, 'Finance')
        self.assertEqual(hr_details.position, 'Accountant')

    def test_salary_details_creation(self):
        """Test salary details creation."""
        salary_details = SalaryDetails.objects.create(
            employee=self.employee,
            basic_salary=Decimal('60000.00'),
            daily_rate=Decimal('2500.00')
        )
        
        self.assertEqual(salary_details.basic_salary, Decimal('60000.00'))
        self.assertEqual(salary_details.daily_rate, Decimal('2500.00'))

    def test_employee_relationships(self):
        """Test employee relationships with HR and salary details."""
        # Test HR details relationship
        self.assertEqual(self.employee.hr_details.first(), self.hr_details)
        self.assertEqual(self.hr_details.employee, self.employee)
        
        # Test salary details relationship
        self.assertEqual(self.employee.salary_details.first(), self.salary_details)
        self.assertEqual(self.salary_details.employee, self.employee)

    def test_employee_activation_deactivation(self):
        """Test employee activation and deactivation."""
        # Initially active
        self.assertTrue(self.employee.is_active)
        
        # Deactivate
        self.employee.is_active = False
        self.employee.save()
        self.assertFalse(self.employee.is_active)
        
        # Reactivate
        self.employee.is_active = True
        self.employee.save()
        self.assertTrue(self.employee.is_active)


class PayrollComponentsTestCase(TestCase):
    """Test cases for payroll components."""
    
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        # Create test employee
        self.employee = Employee.objects.create(
            user=self.user,
            employment_type='permanent',
            date_employed=date(2023, 1, 1)
        )
        
        # Create payroll components
        self.benefit_component = PayrollComponents.objects.create(
            title='Housing Allowance',
            type='benefit',
            category='allowance',
            calculation_method='percentage',
            value=Decimal('15.00'),
            is_active=True
        )
        
        self.deduction_component = PayrollComponents.objects.create(
            title='Loan Repayment',
            type='deduction',
            category='loan',
            calculation_method='fixed',
            value=Decimal('5000.00'),
            is_active=True
        )

    def test_payroll_component_creation(self):
        """Test payroll component creation."""
        component = PayrollComponents.objects.create(
            title='Test Component',
            type='benefit',
            category='test',
            calculation_method='fixed',
            value=Decimal('1000.00'),
            is_active=True
        )
        
        self.assertEqual(component.title, 'Test Component')
        self.assertEqual(component.type, 'benefit')
        self.assertEqual(component.value, Decimal('1000.00'))

    def test_component_types(self):
        """Test different component types."""
        # Test benefit component
        self.assertEqual(self.benefit_component.type, 'benefit')
        self.assertEqual(self.benefit_component.category, 'allowance')
        
        # Test deduction component
        self.assertEqual(self.deduction_component.type, 'deduction')
        self.assertEqual(self.deduction_component.category, 'loan')

    def test_calculation_methods(self):
        """Test calculation methods for components."""
        # Test percentage calculation
        self.assertEqual(self.benefit_component.calculation_method, 'percentage')
        self.assertEqual(self.benefit_component.value, Decimal('15.00'))
        
        # Test fixed calculation
        self.assertEqual(self.deduction_component.calculation_method, 'fixed')
        self.assertEqual(self.deduction_component.value, Decimal('5000.00'))

    def test_component_activation(self):
        """Test component activation and deactivation."""
        component = PayrollComponents.objects.create(
            title='Test Component',
            type='benefit',
            calculation_method='fixed',
            value=Decimal('1000.00'),
            is_active=False
        )
        
        # Initially inactive
        self.assertFalse(component.is_active)
        
        # Activate
        component.is_active = True
        component.save()
        self.assertTrue(component.is_active)

    def test_component_str_representation(self):
        """Test component string representation."""
        expected_str = f"{self.benefit_component.title} ({self.benefit_component.type})"
        self.assertEqual(str(self.benefit_component), expected_str)


class EmployeePayrollIntegrationTestCase(TestCase):
    """Integration tests for employee payroll functionality."""
    
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        # Create test employee
        self.employee = Employee.objects.create(
            user=self.user,
            employment_type='permanent',
            date_employed=date(2023, 1, 1)
        )
        
        # Create salary details
        self.salary_details = SalaryDetails.objects.create(
            employee=self.employee,
            basic_salary=Decimal('50000.00'),
            daily_rate=Decimal('2000.00'),
            hourly_rate=Decimal('250.00')
        )

    def test_employee_payroll_data_integration(self):
        """Test integration between employee and payroll data."""
        # Test that employee has salary details
        self.assertIsNotNone(self.employee.salary_details.first())
        self.assertEqual(self.employee.salary_details.first().basic_salary, Decimal('50000.00'))
        
        # Test daily rate calculation
        daily_rate = self.employee.salary_details.first().daily_rate
        self.assertEqual(daily_rate, Decimal('2000.00'))

    def test_employee_employment_types(self):
        """Test different employment types."""
        # Test permanent employee
        self.assertEqual(self.employee.employment_type, 'permanent')
        
        # Test casual employee
        casual_employee = Employee.objects.create(
            user=self.user,
            employment_type='casual',
            date_employed=date(2024, 1, 1)
        )
        self.assertEqual(casual_employee.employment_type, 'casual')
        
        # Test consultant employee
        consultant_employee = Employee.objects.create(
            user=self.user,
            employment_type='consultant',
            date_employed=date(2024, 1, 1)
        )
        self.assertEqual(consultant_employee.employment_type, 'consultant')

    def test_employee_salary_adjustments(self):
        """Test salary adjustments and updates."""
        # Initial salary
        initial_salary = self.salary_details.basic_salary
        self.assertEqual(initial_salary, Decimal('50000.00'))
        
        # Update salary
        self.salary_details.basic_salary = Decimal('55000.00')
        self.salary_details.save()
        
        # Verify update
        updated_salary = SalaryDetails.objects.get(id=self.salary_details.id).basic_salary
        self.assertEqual(updated_salary, Decimal('55000.00'))

    def test_employee_deactivation_impact(self):
        """Test impact of employee deactivation on related data."""
        # Initially active
        self.assertTrue(self.employee.is_active)
        
        # Deactivate employee
        self.employee.is_active = False
        self.employee.save()
        
        # Verify deactivation
        deactivated_employee = Employee.objects.get(id=self.employee.id)
        self.assertFalse(deactivated_employee.is_active)

    def test_employee_data_consistency(self):
        """Test data consistency across employee-related models."""
        # Test HR details consistency
        hr_details = self.employee.hr_details.first()
        if hr_details:
            self.assertEqual(hr_details.employee, self.employee)
            self.assertEqual(hr_details.employee.user, self.user)
        
        # Test salary details consistency
        salary_details = self.employee.salary_details.first()
        if salary_details:
            self.assertEqual(salary_details.employee, self.employee)
            self.assertEqual(salary_details.employee.user, self.user)
