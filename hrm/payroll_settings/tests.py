from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from datetime import date, datetime
from unittest.mock import patch, MagicMock

from hrm.employees.models import Employee, HRDetails
from hrm.payroll_settings.models import (
    Formulas, FormulaItems, PayrollComponents, 
    ScheduledPayslip, PayrollApprovalWorkflow, PayrollApprovalStep
)

User = get_user_model()


class FormulasTestCase(TestCase):
    """Test cases for payroll formulas."""
    
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
        
        # Create test formulas
        self.income_formula = Formulas.objects.create(
            title='Income Tax 2024',
            type='income',
            version='2024',
            is_active=True,
            is_current=True,
            effective_date=date(2024, 1, 1),
            description='Income tax calculation for 2024'
        )
        
        self.nssf_formula = Formulas.objects.create(
            title='NSSF 2024',
            type='deduction',
            category='social_security_fund',
            version='2024',
            is_active=True,
            is_current=True,
            effective_date=date(2024, 1, 1),
            description='NSSF contribution calculation for 2024'
        )
        
        self.nhif_formula = Formulas.objects.create(
            title='NHIF 2024',
            type='deduction',
            category='nhif',
            version='2024',
            is_active=True,
            is_current=True,
            effective_date=date(2024, 1, 1),
            description='NHIF contribution calculation for 2024'
        )

    def test_formula_creation(self):
        """Test formula creation with all required fields."""
        formula = Formulas.objects.create(
            title='Test Formula',
            type='deduction',
            category='test',
            version='1.0',
            is_active=True,
            is_current=False,
            effective_date=date(2024, 1, 1)
        )
        
        self.assertEqual(formula.title, 'Test Formula')
        self.assertEqual(formula.type, 'deduction')
        self.assertEqual(formula.version, '1.0')
        self.assertTrue(formula.is_active)
        self.assertFalse(formula.is_current)

    def test_formula_versioning(self):
        """Test formula versioning system."""
        # Create multiple versions of the same formula type
        old_formula = Formulas.objects.create(
            title='Income Tax 2023',
            type='income',
            version='2023',
            is_active=True,
            is_current=False,
            effective_date=date(2023, 1, 1)
        )
        
        new_formula = Formulas.objects.create(
            title='Income Tax 2024',
            type='income',
            version='2024',
            is_active=True,
            is_current=True,
            effective_date=date(2024, 1, 1)
        )
        
        # Test that only one formula can be current per type
        self.assertFalse(old_formula.is_current)
        self.assertTrue(new_formula.is_current)
        
        # Test effective date ordering
        self.assertLess(old_formula.effective_date, new_formula.effective_date)

    def test_formula_activation_deactivation(self):
        """Test formula activation and deactivation."""
        formula = Formulas.objects.create(
            title='Test Formula',
            type='deduction',
            version='1.0',
            is_active=False,
            effective_date=date(2024, 1, 1)
        )
        
        # Initially inactive
        self.assertFalse(formula.is_active)
        
        # Activate
        formula.is_active = True
        formula.save()
        self.assertTrue(formula.is_active)
        
        # Deactivate
        formula.is_active = False
        formula.save()
        self.assertFalse(formula.is_active)

    def test_formula_str_representation(self):
        """Test formula string representation."""
        formula = Formulas.objects.create(
            title='Test Formula',
            type='income',
            version='1.0',
            effective_date=date(2024, 1, 1)
        )
        
        expected_str = f"{formula.title} ({formula.version}) - {formula.type}"
        self.assertEqual(str(formula), expected_str)


class FormulaItemsTestCase(TestCase):
    """Test cases for formula items."""
    
    def setUp(self):
        """Set up test data."""
        # Create test formula
        self.formula = Formulas.objects.create(
            title='Test Formula',
            type='income',
            version='1.0',
            is_active=True,
            effective_date=date(2024, 1, 1)
        )
        
        # Create test formula items
        self.percentage_item = FormulaItems.objects.create(
            formula=self.formula,
            component_type='tax',
            calculation_method='percentage',
            value=Decimal('30.00'),
            min_amount=Decimal('0.00'),
            max_amount=Decimal('1000000.00'),
            description='30% tax rate'
        )
        
        self.fixed_item = FormulaItems.objects.create(
            formula=self.formula,
            component_type='deduction',
            calculation_method='fixed',
            value=Decimal('500.00'),
            min_amount=Decimal('0.00'),
            max_amount=Decimal('500.00'),
            description='Fixed deduction of 500'
        )

    def test_formula_item_creation(self):
        """Test formula item creation."""
        item = FormulaItems.objects.create(
            formula=self.formula,
            component_type='benefit',
            calculation_method='percentage',
            value=Decimal('15.00'),
            min_amount=Decimal('0.00'),
            max_amount=Decimal('50000.00')
        )
        
        self.assertEqual(item.formula, self.formula)
        self.assertEqual(item.component_type, 'benefit')
        self.assertEqual(item.calculation_method, 'percentage')
        self.assertEqual(item.value, Decimal('15.00'))

    def test_calculation_methods(self):
        """Test different calculation methods."""
        # Test percentage calculation
        self.assertEqual(self.percentage_item.calculation_method, 'percentage')
        self.assertEqual(self.percentage_item.value, Decimal('30.00'))
        
        # Test fixed calculation
        self.assertEqual(self.fixed_item.calculation_method, 'fixed')
        self.assertEqual(self.fixed_item.value, Decimal('500.00'))

    def test_amount_limits(self):
        """Test amount limits for formula items."""
        # Test percentage item limits
        self.assertEqual(self.percentage_item.min_amount, Decimal('0.00'))
        self.assertEqual(self.percentage_item.max_amount, Decimal('1000000.00'))
        
        # Test fixed item limits
        self.assertEqual(self.fixed_item.min_amount, Decimal('0.00'))
        self.assertEqual(self.fixed_item.max_amount, Decimal('500.00'))

    def test_formula_item_str_representation(self):
        """Test formula item string representation."""
        expected_str = f"{self.percentage_item.component_type} - {self.percentage_item.calculation_method}"
        self.assertEqual(str(self.percentage_item), expected_str)


class PayrollComponentsTestCase(TestCase):
    """Test cases for payroll components."""
    
    def setUp(self):
        """Set up test data."""
        # Create test components
        self.benefit_component = PayrollComponents.objects.create(
            title='Housing Allowance',
            type='benefit',
            category='allowance',
            calculation_method='percentage',
            value=Decimal('15.00'),
            is_active=True,
            description='Housing allowance at 15% of basic salary'
        )
        
        self.deduction_component = PayrollComponents.objects.create(
            title='Loan Repayment',
            type='deduction',
            category='loan',
            calculation_method='fixed',
            value=Decimal('5000.00'),
            is_active=True,
            description='Monthly loan repayment'
        )

    def test_component_creation(self):
        """Test component creation."""
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


class ScheduledPayslipsTestCase(TestCase):
    """Test cases for scheduled payslips."""
    
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
        
        # Create test scheduled payslip
        self.scheduled_payslip = ScheduledPayslip.objects.create(
            document_type='payslip',
            payroll_period=date(2024, 1, 1),
            scheduled_time=timezone.now() + timezone.timedelta(hours=1),
            status='Pending',
            delivery_status='pending',
            composer=self.user,
            comments='Test scheduled payslip'
        )
        self.scheduled_payslip.recipients.add(self.employee)

    def test_scheduled_payslip_creation(self):
        """Test scheduled payslip creation."""
        scheduled = ScheduledPayslip.objects.create(
            document_type='payslip',
            payroll_period=date(2024, 2, 1),
            scheduled_time=timezone.now() + timezone.timedelta(hours=2),
            status='Pending',
            delivery_status='pending',
            composer=self.user
        )
        
        self.assertEqual(scheduled.document_type, 'payslip')
        self.assertEqual(scheduled.status, 'Pending')
        self.assertEqual(scheduled.delivery_status, 'pending')

    def test_scheduled_payslip_status_updates(self):
        """Test scheduled payslip status updates."""
        # Test status progression
        self.assertEqual(self.scheduled_payslip.status, 'Pending')
        
        # Update to processing
        self.scheduled_payslip.status = 'Processing'
        self.scheduled_payslip.save()
        self.assertEqual(self.scheduled_payslip.status, 'Processing')
        
        # Update to sent
        self.scheduled_payslip.status = 'Sent'
        self.scheduled_payslip.save()
        self.assertEqual(self.scheduled_payslip.status, 'Sent')

    def test_delivery_status_updates(self):
        """Test delivery status updates."""
        # Test delivery status progression
        self.assertEqual(self.scheduled_payslip.delivery_status, 'pending')
        
        # Update to delivered
        self.scheduled_payslip.delivery_status = 'delivered'
        self.scheduled_payslip.save()
        self.assertEqual(self.scheduled_payslip.delivery_status, 'delivered')

    def test_recipients_management(self):
        """Test recipients management."""
        # Test adding recipients
        self.assertIn(self.employee, self.scheduled_payslip.recipients.all())
        
        # Test removing recipients
        self.scheduled_payslip.recipients.remove(self.employee)
        self.assertNotIn(self.employee, self.scheduled_payslip.recipients.all())

    def test_scheduled_payslip_str_representation(self):
        """Test scheduled payslip string representation."""
        expected_str = f"Scheduled {self.scheduled_payslip.document_type} for {self.scheduled_payslip.payroll_period}"
        self.assertEqual(str(self.scheduled_payslip), expected_str)


class PayrollApprovalWorkflowTestCase(TestCase):
    """Test cases for payroll approval workflow."""
    
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
        
        # Create test approval workflow
        self.workflow = PayrollApprovalWorkflow.objects.create(
            current_level='level_1',
            overall_status='pending',
            amount_threshold=Decimal('100000.00'),
            requires_finance_approval=True,
            requires_ceo_approval=False,
            submitted_by=self.user,
            comments='Test approval workflow'
        )

    def test_approval_workflow_creation(self):
        """Test approval workflow creation."""
        workflow = PayrollApprovalWorkflow.objects.create(
            current_level='level_1',
            overall_status='pending',
            submitted_by=self.user
        )
        
        self.assertEqual(workflow.current_level, 'level_1')
        self.assertEqual(workflow.overall_status, 'pending')
        self.assertEqual(workflow.submitted_by, self.user)

    def test_approval_levels(self):
        """Test approval level progression."""
        # Test initial level
        self.assertEqual(self.workflow.current_level, 'level_1')
        
        # Test level progression
        self.workflow.current_level = 'level_2'
        self.workflow.save()
        self.assertEqual(self.workflow.current_level, 'level_2')

    def test_approval_status_updates(self):
        """Test approval status updates."""
        # Test status progression
        self.assertEqual(self.workflow.overall_status, 'pending')
        
        # Update to approved
        self.workflow.overall_status = 'approved'
        self.workflow.save()
        self.assertEqual(self.workflow.overall_status, 'approved')

    def test_amount_threshold_handling(self):
        """Test amount threshold handling."""
        # Test with amount below threshold
        workflow = PayrollApprovalWorkflow.objects.create(
            current_level='level_1',
            overall_status='pending',
            amount_threshold=Decimal('50000.00'),
            submitted_by=self.user
        )
        
        self.assertFalse(workflow.requires_finance_approval)
        self.assertFalse(workflow.requires_ceo_approval)
        
        # Test with amount above threshold
        workflow.amount_threshold = Decimal('1000000.00')
        workflow.save()
        
        self.assertTrue(workflow.requires_finance_approval)
        self.assertTrue(workflow.requires_ceo_approval)

    def test_approval_workflow_str_representation(self):
        """Test approval workflow string representation."""
        expected_str = f"Workflow for {self.workflow.content_type} #{self.workflow.object_id} - {self.workflow.overall_status}"
        self.assertEqual(str(self.workflow), expected_str)


class PayrollApprovalStepTestCase(TestCase):
    """Test cases for payroll approval steps."""
    
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
        
        # Create test approval workflow
        self.workflow = PayrollApprovalWorkflow.objects.create(
            current_level='level_1',
            overall_status='pending',
            submitted_by=self.user
        )
        
        # Create test approval step
        self.approval_step = PayrollApprovalStep.objects.create(
            workflow=self.workflow,
            level='level_1',
            approver=self.user,
            status='pending',
            comments='Test approval step'
        )

    def test_approval_step_creation(self):
        """Test approval step creation."""
        step = PayrollApprovalStep.objects.create(
            workflow=self.workflow,
            level='level_2',
            approver=self.user,
            status='pending'
        )
        
        self.assertEqual(step.workflow, self.workflow)
        self.assertEqual(step.level, 'level_2')
        self.assertEqual(step.approver, self.user)

    def test_approval_step_status_updates(self):
        """Test approval step status updates."""
        # Test status progression
        self.assertEqual(self.approval_step.status, 'pending')
        
        # Update to approved
        self.approval_step.status = 'approved'
        self.approval_step.approved_at = timezone.now()
        self.approval_step.save()
        
        self.assertEqual(self.approval_step.status, 'approved')
        self.assertIsNotNone(self.approval_step.approved_at)

    def test_approval_step_rejection(self):
        """Test approval step rejection."""
        # Test rejection
        self.approval_step.status = 'rejected'
        self.approval_step.rejected_at = timezone.now()
        self.approval_step.comments = 'Rejected due to insufficient documentation'
        self.approval_step.save()
        
        self.assertEqual(self.approval_step.status, 'rejected')
        self.assertIsNotNone(self.approval_step.rejected_at)
        self.assertIn('insufficient documentation', self.approval_step.comments)

    def test_approval_step_str_representation(self):
        """Test approval step string representation."""
        expected_str = f"Step {self.approval_step.level} for Workflow #{self.workflow.id} - {self.approval_step.status}"
        self.assertEqual(str(self.approval_step), expected_str)
