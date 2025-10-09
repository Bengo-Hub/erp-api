"""
Enhanced Formula Management Service
Handles formula selection, transitions, and overrides for payroll calculations
"""

from datetime import date
from decimal import Decimal
from django.db.models import Q
from hrm.payroll_settings.models import (
    Formulas, FormulaItems, PayrollComponents, 
    SplitRatio, Relief
)
from .utils import get_formula_effective_date, validate_formula_data


class FormulaManagerService:
    """
    Service for managing payroll formulas and their selection
    """
    
    def __init__(self):
        self.cache = {}
    
    def get_effective_formula(self, formula_type, category=None, payroll_date=None, formula_id=None):
        """
        Get the effective formula for a specific type and date
        
        Args:
            formula_type (str): Type of formula (income, deduction, etc.)
            category (str): Category of formula (primary, secondary, etc.)
            payroll_date (date): Payroll date for formula selection
            formula_id (int): Specific formula ID to override
        
        Returns:
            Formulas: Effective formula instance
        """
        try:
            # Priority 1: Explicit formula ID override
            if formula_id:
                formula = Formulas.objects.filter(
                    id=formula_id,
                    type=formula_type
                ).first()
                if formula:
                    return formula
            
            # Priority 2: Date-based formula selection
            if payroll_date:
                formula = self._get_formula_by_date(formula_type, category, payroll_date)
                if formula:
                    return formula
            
            # Priority 3: Current formula fallback
            formula = self._get_current_formula(formula_type, category)
            if formula:
                return formula
            
            # Priority 4: Any available formula
            formula = self._get_any_formula(formula_type, category)
            return formula
            
        except Exception as e:
            print(f"Error getting effective formula: {e}")
            return None
    
    def _get_formula_by_date(self, formula_type, category, payroll_date):
        """
        Get formula effective for a specific date
        """
        queryset = Formulas.objects.filter(
            type=formula_type,
            effective_from__lte=payroll_date
        )
        
        if category:
            queryset = queryset.filter(category=category)
        
        # Get formula whose effective window contains the date
        formula = queryset.filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=payroll_date)
        ).order_by('-effective_from', '-version').first()
        
        if formula:
            return formula
        
        # Fallback to latest formula <= date
        return queryset.order_by('-effective_from', '-version').first()
    
    def _get_current_formula(self, formula_type, category):
        """
        Get current formula for type and category
        """
        queryset = Formulas.objects.filter(
            type=formula_type,
            is_current=True
        )
        
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset.first()
    
    def _get_any_formula(self, formula_type, category):
        """
        Get any available formula as last resort
        """
        queryset = Formulas.objects.filter(type=formula_type)
        
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset.order_by('-effective_from', '-version').first()
    
    def get_formula_rates(self, formula):
        """
        Get rates from a formula
        
        Args:
            formula (Formulas): Formula instance
        
        Returns:
            list: List of (lower, upper, rate) tuples
        """
        if not formula:
            return []
        
        rates = []
        formula_items = FormulaItems.objects.filter(formula=formula).order_by('amount_from')
        
        for item in formula_items:
            if item.deduct_amount > 0:
                rate = item.deduct_amount
            else:
                rate = item.deduct_percentage / Decimal('100')
            
            rates.append((item.amount_from, item.amount_to, rate))
        
        return rates
    
    def get_formula_relief(self, formula):
        """
        Get relief amount from a formula
        
        Args:
            formula (Formulas): Formula instance
        
        Returns:
            Decimal: Relief amount
        """
        if not formula:
            return Decimal('0')
        
        return formula.personal_relief or Decimal('0')
    
    def get_split_ratio(self, formula):
        """
        Get employee/employer split ratio for a formula
        
        Args:
            formula (Formulas): Formula instance
        
        Returns:
            tuple: (employee_percentage, employer_percentage)
        """
        if not formula:
            return Decimal('100'), Decimal('0')
        
        split_ratio = SplitRatio.objects.filter(formula=formula).first()
        if split_ratio:
            return (
                split_ratio.employee_percentage / Decimal('100'),
                split_ratio.employer_percentage / Decimal('100')
            )
        
        return Decimal('100'), Decimal('0')
    
    def calculate_tax_with_formula(self, taxable_income, formula):
        """
        Calculate tax using a specific formula
        
        Args:
            taxable_income (Decimal): Taxable income amount
            formula (Formulas): Tax formula to use
        
        Returns:
            Decimal: Calculated tax amount
        """
        if not formula or not formula.is_effective_for_date(date.today()):
            return Decimal('0')
        
        total_tax = Decimal('0')
        rates = self.get_formula_rates(formula)
        
        for lower, upper, rate in rates:
            if taxable_income <= lower:
                break
            
            taxable_amount = min(upper - lower, max(Decimal('0'), taxable_income - lower))
            tax_amount = taxable_amount * rate
            total_tax += tax_amount
        
        return total_tax
    
    def get_formula_transition_info(self, old_formula, new_formula):
        """
        Get information about formula transition
        
        Args:
            old_formula (Formulas): Previous formula
            new_formula (Formulas): New formula
        
        Returns:
            dict: Transition information
        """
        if not old_formula or not new_formula:
            return {}
        
        return {
            'old_formula': {
                'title': old_formula.title,
                'version': old_formula.version,
                'effective_to': old_formula.effective_to,
                'regulatory_source': old_formula.regulatory_source
            },
            'new_formula': {
                'title': new_formula.title,
                'version': new_formula.version,
                'effective_from': new_formula.effective_from,
                'regulatory_source': new_formula.regulatory_source
            },
            'transition_date': new_formula.effective_from,
            'notes': new_formula.notes
        }
    
    def validate_formula_override(self, original_formula, override_formula, payroll_date):
        """
        Validate formula override request
        
        Args:
            original_formula (Formulas): Original formula that would be used
            override_formula (Formulas): Formula to override with
            payroll_date (date): Payroll date
        
        Returns:
            tuple: (is_valid, error_message)
        """
        if not override_formula:
            return False, "Override formula is required"
        
        if not override_formula.is_effective_for_date(payroll_date):
            return False, "Override formula is not effective for the payroll date"
        
        if override_formula.type != original_formula.type:
            return False, "Override formula must be of the same type"
        
        if override_formula.category != original_formula.category:
            return False, "Override formula must be of the same category"
        
        return True, ""
    
    def get_formula_history(self, formula_type, category=None, start_date=None, end_date=None):
        """
        Get formula history for a specific type and period
        
        Args:
            formula_type (str): Type of formula
            category (str): Category of formula
            start_date (date): Start date for history
            end_date (date): End date for history
        
        Returns:
            QuerySet: Formula history
        """
        queryset = Formulas.objects.filter(type=formula_type)
        
        if category:
            queryset = queryset.filter(category=category)
        
        if start_date:
            queryset = queryset.filter(effective_from__gte=start_date)
        
        if end_date:
            queryset = queryset.filter(effective_to__lte=end_date)
        
        return queryset.order_by('-effective_from', '-version')
    
    def get_active_formulas(self, formula_type=None, category=None):
        """
        Get all currently active formulas
        
        Args:
            formula_type (str): Type of formula to filter by
            category (str): Category of formula to filter by
        
        Returns:
            QuerySet: Active formulas
        """
        queryset = Formulas.objects.filter(is_current=True)
        
        if formula_type:
            queryset = queryset.filter(type=formula_type)
        
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset.order_by('type', 'category')
    
    def deactivate_formula(self, formula_id):
        """
        Deactivate a formula
        
        Args:
            formula_id (int): ID of formula to deactivate
        
        Returns:
            bool: Success status
        """
        try:
            formula = Formulas.objects.get(id=formula_id)
            formula.is_current = False
            formula.save()
            return True
        except Formulas.DoesNotExist:
            return False
    
    def activate_formula(self, formula_id):
        """
        Activate a formula (deactivates others of same type/category)
        
        Args:
            formula_id (int): ID of formula to activate
        
        Returns:
            bool: Success status
        """
        try:
            formula = Formulas.objects.get(id=formula_id)
            
            # Deactivate other formulas of same type and category
            Formulas.objects.filter(
                type=formula.type,
                category=formula.category
            ).update(is_current=False)
            
            # Activate this formula
            formula.is_current = True
            formula.save()
            
            return True
        except Formulas.DoesNotExist:
            return False
    
    def get_formula_summary(self, formula):
        """
        Get summary information about a formula
        
        Args:
            formula (Formulas): Formula instance
        
        Returns:
            dict: Formula summary
        """
        if not formula:
            return {}
        
        rates = self.get_formula_rates(formula)
        employee_pct, employer_pct = self.get_split_ratio(formula)
        
        return {
            'id': formula.id,
            'title': formula.title,
            'type': formula.type,
            'category': formula.category,
            'version': formula.version,
            'effective_from': formula.effective_from,
            'effective_to': formula.effective_to,
            'is_current': formula.is_current,
            'is_historical': formula.is_historical,
            'personal_relief': formula.personal_relief,
            'regulatory_source': formula.regulatory_source,
            'notes': formula.notes,
            'rates_count': len(rates),
            'employee_percentage': employee_pct * 100,
            'employer_percentage': employer_pct * 100,
            'rates': rates
        }
