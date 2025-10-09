"""
Centralized Payroll Calculation Engine
This module contains all core payroll calculation logic, eliminating duplication
and providing a single source of truth for all payroll computations.
"""

from decimal import Decimal
from datetime import date
from django.db.models import Q
from hrm.payroll_settings.models import Formulas, FormulaItems, SplitRatio, Relief
from hrm.employees.models import SalaryDetails
from ..models import EmployeLoans, Advances, LossesAndDamages, Benefits


class PayrollCalculationEngine:
    """
    Centralized engine for all payroll calculations
    Eliminates duplication and provides consistent calculation logic
    """
    
    def __init__(self, payment_period: date, formula_overrides: dict = None):
        self.payment_period = payment_period
        self.formula_overrides = formula_overrides or {}
    
    def get_effective_formula(self, formula_type: str, category: str = None, title: str = None):
        """
        Get the effective formula for a specific type, category, and title
        Centralized formula retrieval logic
        """
        try:
            # First check if there's a formula override
            if self.formula_overrides.get(formula_type):
                formula = Formulas.objects.filter(
                    id=self.formula_overrides[formula_type],
                    is_current=True
                ).first()
                if formula:
                    return formula
            
            # Build query for effective formula
            query = Q(type=formula_type, is_current=True)
            if category:
                query &= Q(category=category)
            if title:
                query &= Q(title__icontains=title)
            
            # Find formula effective for the payment period
            for formula in Formulas.objects.filter(query).order_by('-effective_from'):
                if formula.is_effective_for_date(self.payment_period):
                    return formula
            
            # Fallback to current formula if no effective formula found
            return Formulas.objects.filter(query).first()
            
        except Exception as e:
            print(f"Error getting effective formula for {formula_type}: {e}")
            return None
    
    def load_formula_rates(self, formula_type: str, category: str = None, title: str = None):
        """
        Load formula rates and split ratios for calculations
        Centralized rate loading logic
        """
        try:
            formula = self.get_effective_formula(formula_type, category, title)
            if not formula:
                return [], Decimal('0'), Decimal('1'), Decimal('0')
            
            rates = []
            applicable_relief = Decimal('0')
            
            # Calculate relief if applicable
            if formula.deduction:
                relief = formula.deduction.applicable_relief
                if relief and relief.is_active:
                    applicable_relief = relief.percentage
            
            # Extract formula rates
            formula_items = FormulaItems.objects.filter(formula=formula).order_by('amount_from')
            for item in formula_items:
                rate = item.deduct_amount if item.deduct_amount > 0 else item.deduct_percentage / Decimal('100')
                rates.append((item.amount_from, item.amount_to, rate))
            
            # Add upper limit only for non-income formulas
            if formula_type != 'income':
                upper_rate = formula.upper_limit_amount if formula.upper_limit_amount > 0 else formula.upper_limit_percentage / Decimal('100')
                rates.append((formula.upper_limit, Decimal('inf'), upper_rate))
            
            # Get split ratios
            split_ratios = SplitRatio.objects.filter(formula=formula).first()
            employee_percentage = split_ratios.employee_percentage / Decimal('100') if split_ratios else Decimal('1')
            employer_percentage = split_ratios.employer_percentage / Decimal('100') if split_ratios else Decimal('0')
            
            return rates, applicable_relief / Decimal('100'), employee_percentage, employer_percentage
            
        except Exception as e:
            print(f"Error loading {formula_type} rates: {e}")
            return [], Decimal('0'), Decimal('1'), Decimal('0')
    
    def calculate_income_tax(self, taxable_pay: Decimal, employee_category: str = 'primary'):
        """
        Calculate income tax using progressive tax brackets
        """
        if taxable_pay <= Decimal('0'):
            return Decimal('0')
        
        tax_brackets, relief, _, _ = self.load_formula_rates('income', employee_category)
        
        total_tax = Decimal('0')
        tax_brackets = sorted(tax_brackets, key=lambda x: x[0])
        
        for lower, upper, rate in tax_brackets:
            if taxable_pay <= lower:
                continue
            
            taxable_amount = min(upper - lower, max(Decimal('0'), taxable_pay - lower))
            tax_amount = taxable_amount * Decimal(rate)
            total_tax += tax_amount
            
            if taxable_pay <= upper:
                break
        
        return Decimal(total_tax)
    
    def calculate_nssf_contribution(self, salary: Decimal):
        """
        Calculate NSSF contributions using current rates
        """
        nssf_rates, _, employee_percentage, employer_percentage = self.load_formula_rates(
            'deduction', title='n.s.s.f'
        )
        
        tier_1_employee = tier_2_employee = tier_1_employer = tier_2_employer = Decimal('0')
        nssf_rates = sorted(nssf_rates, key=lambda x: x[0])
        processed_brackets = set()
        
        for lower, upper, rate in nssf_rates:
            bracket_key = (lower, upper)
            if bracket_key in processed_brackets:
                continue
            processed_brackets.add(bracket_key)
            
            if salary > lower:
                taxable_amount = min(upper - lower, max(Decimal('0'), salary - lower))
                total_contribution = taxable_amount * rate
                
                employee_contribution = total_contribution * employee_percentage
                employer_contribution = total_contribution * employer_percentage
                
                if lower == Decimal('0'):  # Tier 1
                    tier_1_employee += employee_contribution
                    tier_1_employer += employer_contribution
                elif lower == Decimal('8000'):  # Tier 2
                    tier_2_employee += employee_contribution
                    tier_2_employer += employer_contribution
        
        # Round contributions
        tier_1_employee = round(tier_1_employee)
        tier_2_employee = round(tier_2_employee)
        tier_1_employer = round(tier_1_employer)
        tier_2_employer = round(tier_2_employer)
        
        return {
            'tier_1_employee': tier_1_employee,
            'tier_2_employee': tier_2_employee,
            'tier_1_employer': tier_1_employer,
            'tier_2_employer': tier_2_employer,
            'total_employee': tier_1_employee + tier_2_employee,
            'total_employer': tier_1_employer + tier_2_employer
        }
    
    def calculate_shif_contribution(self, salary: Decimal):
        """
        Calculate SHIF contributions (2025+)
        """
        shif_rates, applicable_relief, employee_percentage, employer_percentage = self.load_formula_rates(
            'deduction', title='s.h.i.f'
        )
        
        relief = Decimal('0')
        employee_contribution = Decimal('0')
        employer_contribution = Decimal('0')
        
        shif_rates = sorted(shif_rates, key=lambda x: x[0])
        
        for lower, upper, rate in shif_rates:
            if salary > lower:
                taxable_amount = min(upper - lower, max(Decimal('0'), salary - lower))
                total_contribution = taxable_amount * rate
                
                employee_contribution = total_contribution * employee_percentage
                employer_contribution = total_contribution * employer_percentage
                
                # SHIF relief repealed as of Dec 2024
                relief = Decimal('0')
                break
        
        return {
            'employee_contribution': round(employee_contribution, 2),
            'employer_contribution': round(employer_contribution, 2),
            'relief': relief
        }
    
    def calculate_nhif_contribution(self, salary: Decimal):
        """
        Calculate NHIF contributions (legacy, pre-2025)
        """
        nhif_rates, insurance_relief, employee_percentage, employer_percentage = self.load_formula_rates(
            'deduction', title='n.h.i.f'
        )
        
        relief = Decimal('0')
        employee_contribution = Decimal('0')
        employer_contribution = Decimal('0')
        
        if len(nhif_rates) > 0:
            for lower, upper, contribution in nhif_rates:
                if lower <= salary <= upper:
                    if contribution < 1:
                        contribution = salary * contribution
                    
                    employee_contribution = contribution * employee_percentage
                    employer_contribution = contribution * employer_percentage
                    
                    # NHIF relief was repealed Dec 2024
                    if self.payment_period < date(2024, 12, 1):
                        relief = insurance_relief * employee_contribution
                    break
        else:
            # Fallback to legacy NHIF rates
            employee_contribution = self._get_legacy_nhif_rate(salary)
            employer_contribution = employee_contribution
        
        return {
            'employee_contribution': round(employee_contribution, 2),
            'employer_contribution': round(employer_contribution, 2),
            'relief': relief
        }
    
    def calculate_housing_levy(self, salary: Decimal):
        """
        Calculate Housing Levy (1.5% of gross salary)
        """
        levy_rates, applicable_relief, employee_percentage, employer_percentage = self.load_formula_rates(
            'deduction', title='housing'
        )
        
        relief = Decimal('0')
        employee_contribution = Decimal('0')
        employer_contribution = Decimal('0')
        
        levy_rates = sorted(levy_rates, key=lambda x: x[0])
        
        for lower, upper, rate in levy_rates:
            if salary > lower:
                taxable_amount = min(upper - lower, max(Decimal('0'), salary - lower))
                total_contribution = taxable_amount * rate
                
                employee_contribution = total_contribution * employee_percentage
                employer_contribution = total_contribution * employer_percentage
                
                # Housing Levy relief repealed as of Dec 2024
                relief = Decimal('0')
                break
        
        return {
            'employee_contribution': round(employee_contribution, 2),
            'employer_contribution': round(employer_contribution, 2),
            'relief': relief
        }
    
    def calculate_employee_deductions(self, employee, gross_pay: Decimal):
        """
        Calculate all employee-specific deductions (loans, advances, etc.)
        """
        total_loans = Decimal('0')
        total_advances = Decimal('0')
        total_loss_damages = Decimal('0')
        total_benefits = Decimal('0')
        
        try:
            # Calculate loans
            active_loans = EmployeLoans.objects.filter(
                employee=employee,
                is_active=True
            )
            for loan in active_loans:
                if loan.monthly_installment:
                    total_loans += loan.monthly_installment
            
            # Calculate advances
            active_advances = Advances.objects.filter(
                employee=employee,
                is_active=True
            )
            for advance in active_advances:
                # Calculate monthly deduction based on repay_option
                if advance.repay_option and advance.repay_option.no_of_installments > 0:
                    monthly_deduction = advance.repay_option.amount / advance.repay_option.no_of_installments
                    total_advances += monthly_deduction
            
            # Calculate loss/damages
            active_loss_damages = LossesAndDamages.objects.filter(
                employee=employee,
                is_active=True
            )
            for loss_damage in active_loss_damages:
                # Calculate monthly deduction based on repay_option
                if loss_damage.repay_option and loss_damage.repay_option.no_of_installments > 0:
                    monthly_deduction = loss_damage.repay_option.amount / loss_damage.repay_option.no_of_installments
                    total_loss_damages += monthly_deduction
            
            # Calculate non-cash benefits
            active_benefits = Benefits.objects.filter(
                employee=employee,
                is_active=True,
                benefit__non_cash=True
            )
            for benefit in active_benefits:
                if benefit.amount:
                    total_benefits += benefit.amount
        
        except Exception as e:
            print(f"Error calculating employee deductions: {e}")
        
        return {
            'loans': total_loans,
            'advances': total_advances,
            'loss_damages': total_loss_damages,
            'non_cash_benefits': total_benefits
        }
    
    def _get_legacy_nhif_rate(self, salary: Decimal):
        """
        Get legacy NHIF rate based on salary brackets
        """
        if salary <= Decimal('5999'):
            return Decimal('150')
        elif salary <= Decimal('7999'):
            return Decimal('300')
        elif salary <= Decimal('11999'):
            return Decimal('400')
        elif salary <= Decimal('14999'):
            return Decimal('500')
        elif salary <= Decimal('19999'):
            return Decimal('600')
        elif salary <= Decimal('24999'):
            return Decimal('750')
        elif salary <= Decimal('29999'):
            return Decimal('850')
        elif salary <= Decimal('34999'):
            return Decimal('900')
        elif salary <= Decimal('39999'):
            return Decimal('950')
        elif salary <= Decimal('44999'):
            return Decimal('1000')
        elif salary <= Decimal('49999'):
            return Decimal('1100')
        elif salary <= Decimal('59999'):
            return Decimal('1200')
        elif salary <= Decimal('69999'):
            return Decimal('1300')
        elif salary <= Decimal('79999'):
            return Decimal('1400')
        elif salary <= Decimal('89999'):
            return Decimal('1500')
        elif salary <= Decimal('99999'):
            return Decimal('1600')
        else:
            return Decimal('1700')
