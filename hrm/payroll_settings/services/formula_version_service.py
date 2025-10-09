"""
Formula Version Service
Handles formula versioning, transitions, and historical formula management
"""

from datetime import date
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from hrm.payroll_settings.models import Formulas, FormulaItems, Relief


class FormulaVersionService:
    """
    Service for managing formula versions and transitions
    """
    
    def __init__(self):
        self.current_date = date.today()
    
    def get_effective_formula(self, formula_type, category=None, payroll_date=None, formula_id=None):
        """
        Get the effective formula for a specific payroll date
        
        Args:
            formula_type (str): Type of formula (income, deduction, etc.)
            category (str): Category of formula (primary, secondary, etc.)
            payroll_date (date): Date for which to get the formula
            formula_id (int): Specific formula ID to use (override)
        
        Returns:
            Formulas: The effective formula for the given date
        """
        try:
            queryset = Formulas.objects.filter(type=formula_type)
            
            if category:
                queryset = queryset.filter(category=category)
            
            # If specific formula ID provided, use it
            if formula_id:
                return queryset.filter(id=formula_id).first()
            
            # If no payroll date provided, use current date
            if not payroll_date:
                payroll_date = self.current_date
            
            # Find formula effective for the payroll date
            effective_formula = queryset.filter(
                (Q(effective_from__isnull=True) | Q(effective_from__lte=payroll_date))
                & (Q(effective_to__isnull=True) | Q(effective_to__gte=payroll_date))
            ).order_by('-effective_from', '-version').first()
            
            # Fallback to current formula if no effective formula found
            if not effective_formula:
                effective_formula = queryset.filter(is_current=True).first()
            
            return effective_formula
            
        except Exception as e:
            print(f"Error getting effective formula: {e}")
            return None
    
    def get_formula_history(self, formula_type, category=None, start_date=None, end_date=None):
        """
        Get formula history for a specific period
        
        Args:
            formula_type (str): Type of formula
            category (str): Category of formula
            start_date (date): Start date for history
            end_date (date): End date for history
        
        Returns:
            list: List of formulas in chronological order
        """
        try:
            queryset = Formulas.objects.filter(type=formula_type)
            
            if category:
                queryset = queryset.filter(category=category)
            
            if start_date:
                queryset = queryset.filter(effective_from__gte=start_date)
            
            if end_date:
                queryset = queryset.filter(effective_to__lte=end_date)
            
            return queryset.order_by('effective_from', 'version')
            
        except Exception as e:
            print(f"Error getting formula history: {e}")
            return []
    
    def handle_formula_transition(self, old_formula, new_formula, transition_date):
        """
        Handle transition from old formula to new formula
        
        Args:
            old_formula (Formulas): The old formula
            new_formula (Formulas): The new formula
            transition_date (date): Date of transition
        
        Returns:
            bool: Success status
        """
        try:
            with transaction.atomic():
                # Update old formula end date
                if old_formula:
                    old_formula.effective_to = transition_date
                    old_formula.is_current = False
                    old_formula.save()
                
                # Update new formula start date and current status
                if new_formula:
                    new_formula.effective_from = transition_date
                    new_formula.is_current = True
                    new_formula.transition_date = transition_date
                    new_formula.replaces_formula = old_formula
                    new_formula.save()
                
                return True
                
        except Exception as e:
            print(f"Error handling formula transition: {e}")
            return False
    
    def validate_formula_compatibility(self, formula1, formula2):
        """
        Validate if two formulas are compatible for transition
        
        Args:
            formula1 (Formulas): First formula
            formula2 (Formulas): Second formula
        
        Returns:
            dict: Validation result with details
        """
        try:
            validation_result = {
                'compatible': True,
                'issues': [],
                'warnings': []
            }
            
            # Check if formulas are of same type
            if formula1.type != formula2.type:
                validation_result['compatible'] = False
                validation_result['issues'].append(f"Formula types don't match: {formula1.type} vs {formula2.type}")
            
            # Check if formulas are of same category
            if formula1.category != formula2.category:
                validation_result['warnings'].append(f"Formula categories don't match: {formula1.category} vs {formula2.category}")
            
            # Check for overlapping effective periods
            if formula1.effective_from and formula2.effective_from:
                if formula1.effective_from <= formula2.effective_from:
                    if formula1.effective_to and formula2.effective_from <= formula1.effective_to:
                        validation_result['issues'].append("Overlapping effective periods detected")
            
            return validation_result
            
        except Exception as e:
            return {
                'compatible': False,
                'issues': [f"Validation error: {e}"],
                'warnings': []
            }
    
    def get_relief_status(self, relief_type, payroll_date=None):
        """
        Get relief status for a specific date
        
        Args:
            relief_type (str): Type of relief
            payroll_date (date): Date to check relief status
        
        Returns:
            dict: Relief status information
        """
        try:
            if not payroll_date:
                payroll_date = self.current_date
            
            relief = Relief.objects.filter(
                title__icontains=relief_type
            ).first()
            
            if not relief:
                return {
                    'active': False,
                    'amount': Decimal('0'),
                    'reason': 'Relief not found'
                }
            
            # Check if relief is repealed based on date
            relief_status = {
                'active': relief.is_active,
                'amount': relief.fixed_limit or Decimal('0'),
                'percentage': relief.percentage or Decimal('0'),
                'type': relief.type,
                'limit': relief.fixed_limit
            }
            
            # Special handling for repealed reliefs
            if relief_type.lower() in ['shif', 'housing levy', 'ahl'] and payroll_date >= date(2024, 12, 1):
                relief_status['active'] = False
                relief_status['reason'] = 'Relief repealed effective Dec 2024'
            
            return relief_status
            
        except Exception as e:
            return {
                'active': False,
                'amount': Decimal('0'),
                'reason': f'Error checking relief status: {e}'
            }
    
    def migrate_formulas_to_new_version(self, new_version, formula_type=None, category=None):
        """
        Migrate formulas to a new version
        
        Args:
            new_version (str): New version number
            formula_type (str): Type of formulas to migrate
            category (str): Category of formulas to migrate
        
        Returns:
            dict: Migration result
        """
        try:
            with transaction.atomic():
                queryset = Formulas.objects.all()
                
                if formula_type:
                    queryset = queryset.filter(type=formula_type)
                
                if category:
                    queryset = queryset.filter(category=category)
                
                migrated_count = 0
                errors = []
                
                for formula in queryset:
                    try:
                        # Create new version
                        new_formula = Formulas.objects.create(
                            type=formula.type,
                            category=formula.category,
                            title=f"{formula.title} (v{new_version})",
                            unit=formula.unit,
                            effective_from=formula.effective_from,
                            effective_to=formula.effective_to,
                            personal_relief=formula.personal_relief,
                            version=new_version,
                            is_current=False,
                            is_historical=True,
                            regulatory_source=formula.regulatory_source,
                            notes=formula.notes
                        )
                        
                        # Copy formula items
                        for item in formula.formulaitems.all():
                            FormulaItems.objects.create(
                                formula=new_formula,
                                amount_from=item.amount_from,
                                amount_to=item.amount_to,
                                deduct_amount=item.deduct_amount,
                                deduct_percentage=item.deduct_percentage
                            )
                        
                        migrated_count += 1
                        
                    except Exception as e:
                        errors.append(f"Error migrating formula {formula.title}: {e}")
                
                return {
                    'success': len(errors) == 0,
                    'migrated_count': migrated_count,
                    'errors': errors
                }
                
        except Exception as e:
            return {
                'success': False,
                'migrated_count': 0,
                'errors': [f"Migration failed: {e}"]
            }
