"""
Tests for Dynamic Deduction Engine
"""
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from datetime import date
from hrm.payroll_settings.models import Formulas, FormulaItems, PayrollComponents
from hrm.employees.models import Employee, SalaryDetails, CustomUser
from hrm.payroll.services.dynamic_deduction_engine import DynamicDeductionEngine


class DynamicDeductionEngineTest(TestCase):
    """Test the Dynamic Deduction Engine functionality"""
    
    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = CustomUser.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test formulas with different deduction orders
        self.income_formula_2025 = Formulas.objects.create(
            title='PAYE 2025 Onwards',
            type='income',
            category='primary',
            version='2025.1',
            effective_from=date(2025, 1, 1),
            deduction_order=[
                {"phase": "before_tax", "components": ["nssf", "shif", "housing_levy"]},
                {"phase": "after_tax", "components": ["paye"]},
                {"phase": "after_paye", "components": ["loans", "advances"]}
            ]
        )
        
        self.income_formula_2023 = Formulas.objects.create(
            title='PAYE 2023',
            type='income',
            category='primary',
            version='2023.1',
            effective_from=date(2023, 1, 1),
            effective_to=date(2024, 12, 31),
            deduction_order=[
                {"phase": "before_tax", "components": ["nssf"]},
                {"phase": "after_tax", "components": ["paye"]},
                {"phase": "after_paye", "components": ["shif", "housing_levy", "loans"]}
            ]
        )
        
        # Create NSSF formula
        self.nssf_formula = Formulas.objects.create(
            title='NSSF 2025 Onwards',
            type='deduction',
            category='social_security_fund',
            version='2025.1',
            effective_from=date(2025, 1, 1)
        )
        
        # Create SHIF formula
        self.shif_formula = Formulas.objects.create(
            title='SHIF 2025 Onwards',
            type='deduction',
            category='shif',
            version='2025.1',
            effective_from=date(2025, 1, 1)
        )
        
        # Create Housing Levy formula
        self.housing_formula = Formulas.objects.create(
            title='Housing Levy 2025 Onwards',
            type='deduction',
            category='housing_levy',
            version='2025.1',
            effective_from=date(2025, 1, 1)
        )
    
    def test_formula_effective_date_checking(self):
        """Test that formulas correctly identify their effective dates"""
        today = timezone.now().date()
        
        # Test 2025 formula (current)
        self.assertTrue(self.income_formula_2025.is_effective_for_date(date(2025, 6, 1)))
        self.assertFalse(self.income_formula_2025.is_effective_for_date(date(2024, 12, 31)))
        
        # Test 2023 formula (historical)
        self.assertTrue(self.income_formula_2023.is_effective_for_date(date(2023, 6, 1)))
        self.assertFalse(self.income_formula_2023.is_effective_for_date(date(2025, 1, 1)))
        self.assertTrue(self.income_formula_2023.is_historical)
    
    def test_deduction_order_parsing(self):
        """Test that deduction order JSON is correctly parsed"""
        deduction_order = self.income_formula_2025.deduction_order
        
        self.assertEqual(len(deduction_order), 3)
        self.assertEqual(deduction_order[0]['phase'], 'before_tax')
        self.assertEqual(deduction_order[0]['components'], ['nssf', 'shif', 'housing_levy'])
        self.assertEqual(deduction_order[1]['phase'], 'after_tax')
        self.assertEqual(deduction_order[1]['components'], ['paye'])
    
    def test_formula_versioning(self):
        """Test that formula versioning works correctly"""
        self.assertEqual(self.income_formula_2025.version, '2025.1')
        self.assertEqual(self.income_formula_2023.version, '2023.1')
        
        # Test string representation includes version
        self.assertIn('v2025.1', str(self.income_formula_2025))
        self.assertIn('v2023.1', str(self.income_formula_2023))
    
    def test_deduction_phase_choices(self):
        """Test that PayrollComponents have correct deduction phase choices"""
        component = PayrollComponents.objects.create(
            title='Test Component',
            category='Deductions',
            deduction_phase='before_tax',
            deduction_priority=1
        )
        
        self.assertEqual(component.deduction_phase, 'before_tax')
        self.assertEqual(component.deduction_priority, 1)
        
        # Test choices are valid
        valid_phases = [choice[0] for choice in PayrollComponents._meta.get_field('deduction_phase').choices]
        self.assertIn('before_tax', valid_phases)
        self.assertIn('after_tax', valid_phases)
        self.assertIn('after_paye', valid_phases)
        self.assertIn('final', valid_phases)
