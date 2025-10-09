"""
Utility functions for payroll settings services
"""

import random
import string
from decimal import Decimal
from django.contrib.auth import get_user_model
from hrm.employees.models import Employee

User = get_user_model()


def generate_random_code(prefix):
    """
    Generate a random code with prefix
    
    Args:
        prefix (str): Prefix for the code (e.g., 'D' for deductions, 'E' for earnings)
    
    Returns:
        str: Generated code (e.g., 'D00123')
    """
    random_number = random.randint(1, 99999)
    formatted_number = f"{random_number:05}"
    return f"{prefix}{formatted_number}"


def validate_formula_data(formula_data):
    """
    Validate formula data before creation
    
    Args:
        formula_data (dict): Formula data to validate
    
    Returns:
        tuple: (is_valid, error_message)
    """
    required_fields = ['title', 'type', 'effective_from']
    
    for field in required_fields:
        if field not in formula_data or not formula_data[field]:
            return False, f"Missing required field: {field}"
    
    return True, None


def get_formula_effective_date(formula):
    """
    Get the effective date for a formula
    
    Args:
        formula: Formula object
    
    Returns:
        date: Effective date
    """
    if hasattr(formula, 'effective_from') and formula.effective_from:
        return formula.effective_from
    elif hasattr(formula, 'created_at'):
        return formula.created_at.date()
    else:
        from datetime import date
        return date.today()


def get_approval_thresholds():
    """
    Get approval thresholds for different payroll types
    
    Returns:
        dict: Thresholds for different approval levels
    """
    return {
        'supervisor_approval': Decimal('0'),  # Always required
        'hr_approval': Decimal('50000'),      # Above 50K
        'finance_approval': Decimal('100000'), # Above 100K
        'director_approval': Decimal('1000000'), # Above 1M
        'ceo_approval': Decimal('5000000'),   # Above 5M
    }


def get_approver_by_role_and_department(role, department=None):
    """
    Get approver user based on role and department
    
    Args:
        role (str): Role name (e.g., 'supervisor', 'hr_manager', 'finance_manager')
        department: Department object (optional)
    
    Returns:
        User: Approver user or None
    """
    try:
        # First try to find by role and department
        if department:
            employee = Employee.objects.filter(
                user__groups__name__icontains=role,
                department=department,
                is_active=True
            ).first()
            
            if employee:
                return employee.user
        
        # Fallback to role only
        employee = Employee.objects.filter(
            user__groups__name__icontains=role,
            is_active=True
        ).first()
        
        if employee:
            return employee.user
        
        # Try direct user lookup
        user = User.objects.filter(
            groups__name__icontains=role,
            is_active=True
        ).first()
        
        return user
        
    except Exception as e:
        print(f"Error getting approver for role {role}: {e}")
        return None


def get_approval_workflow_config(payroll_type):
    """
    Get approval workflow configuration for payroll type
    
    Args:
        payroll_type (str): Type of payroll ('payslip', 'casual_voucher', 'consultant_voucher')
    
    Returns:
        dict: Workflow configuration
    """
    configs = {
        'payslip': {
            'name': 'Payroll Payslip Approval',
            'description': 'Standard approval workflow for regular employee payslips',
            'requires_multiple_approvals': True,
            'approval_order_matters': True,
            'steps': [
                {'name': 'Supervisor Review', 'role': 'supervisor', 'required': True},
                {'name': 'HR Manager Review', 'role': 'hr_manager', 'required': True},
                {'name': 'Finance Review', 'role': 'finance_manager', 'required': True},
                {'name': 'Director Approval', 'role': 'director', 'required': False}
            ]
        },
        'casual_voucher': {
            'name': 'Casual Voucher Approval',
            'description': 'Approval workflow for casual employee payments',
            'requires_multiple_approvals': True,
            'approval_order_matters': True,
            'steps': [
                {'name': 'Supervisor Review', 'role': 'supervisor', 'required': True},
                {'name': 'HR Manager Review', 'role': 'hr_manager', 'required': True},
                {'name': 'Finance Review', 'role': 'finance_manager', 'required': True}
            ]
        },
        'consultant_voucher': {
            'name': 'Consultant Voucher Approval',
            'description': 'Approval workflow for consultant payments',
            'requires_multiple_approvals': True,
            'approval_order_matters': True,
            'steps': [
                {'name': 'Supervisor Review', 'role': 'supervisor', 'required': True},
                {'name': 'HR Manager Review', 'role': 'hr_manager', 'required': True},
                {'name': 'Finance Review', 'role': 'finance_manager', 'required': True}
            ]
        }
    }
    
    return configs.get(payroll_type, configs['payslip'])


def calculate_approval_urgency(amount):
    """
    Calculate urgency level based on amount
    
    Args:
        amount (Decimal): Amount for approval
    
    Returns:
        str: Urgency level ('low', 'normal', 'high', 'urgent')
    """
    if amount >= Decimal('1000000'):
        return 'urgent'
    elif amount >= Decimal('500000'):
        return 'high'
    elif amount >= Decimal('100000'):
        return 'normal'
    else:
        return 'low'


def get_payroll_content_types():
    """
    Get content types for payroll models
    
    Returns:
        dict: Content types for payroll models
    """
    from django.contrib.contenttypes.models import ContentType
    from hrm.payroll.models import Payslip
    
    return {
        'payslip': ContentType.objects.get_for_model(Payslip),
        # Note: CasualVoucher and ConsultantVoucher models may not exist yet
        # They will be added when those models are created
    }
