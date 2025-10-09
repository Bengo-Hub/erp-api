"""
Payroll Calculation Service
Clean calculation functions that delegate to the centralized engine
"""

import math
import random
import string
from hrm.payroll.models import *
from datetime import date
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q
from hrm.payroll_settings.models import *
from .services.core_calculations import PayrollCalculationEngine


def load_rates(category=None, title=None, type='', effective_date=None, formula_id=None):
    """Load formula rates and split ratios for payroll calculations"""
    try:
        formula_overrides = {}
        if formula_id:
            formula_overrides[type] = formula_id
        
        engine = PayrollCalculationEngine(effective_date or date.today(), formula_overrides)
        return engine.load_formula_rates(type, category, title)
        
    except Exception as e:
        print(f"Error loading {type} rates: {e}")
        return [], Decimal('0'), Decimal('1'), Decimal('0')
  
def calculate_income_tax(taxable_pay, employee_category='primary', effective_date=None, formula_id=None):
    """Calculate income tax using progressive tax brackets"""
    try:
        formula_overrides = {}
        if formula_id:
            formula_overrides['income'] = formula_id
        
        engine = PayrollCalculationEngine(effective_date or date.today(), formula_overrides)
        return engine.calculate_income_tax(taxable_pay, employee_category)
        
    except Exception as e:
        print(f"Error calculating income tax: {e}")
        return Decimal('0')
  
def calculate_nssf_contribution(salary, title='n.s.s.f', effective_date=None, formula_id=None):
    """Calculate NSSF contributions using current rates"""
    try:
        formula_overrides = {}
        if formula_id:
            formula_overrides['nssf'] = formula_id
        
        engine = PayrollCalculationEngine(effective_date or date.today(), formula_overrides)
        nssf_data = engine.calculate_nssf_contribution(salary)
        
        return (
            nssf_data['tier_1_employee'],
            nssf_data['tier_2_employee'],
            nssf_data['total_employer']
        )
        
    except Exception as e:
        print(f"Error calculating NSSF contribution: {e}")
        return Decimal('0'), Decimal('0'), Decimal('0')

def get_deduction_amount(component: PayrollComponents, deduction_item: Deductions, monthly_salary, effective_date=None, formula_id=None):
    """Get deduction amount for a specific component"""
    try:
        formula_overrides = {}
        if formula_id:
            formula_overrides[component.type] = formula_id
        
        engine = PayrollCalculationEngine(effective_date or date.today(), formula_overrides)
        
        # Route to appropriate calculation method based on component type
        if component.type == 'nssf':
            nssf_data = engine.calculate_nssf_contribution(monthly_salary)
            return nssf_data['total_employee']
        elif component.type == 'nhif':
            nhif_data = engine.calculate_nhif_contribution(monthly_salary)
            return nhif_data['employee_contribution']
        elif component.type == 'shif':
            shif_data = engine.calculate_shif_contribution(monthly_salary)
            return shif_data['employee_contribution']
        elif component.type == 'housing_levy':
            levy_data = engine.calculate_housing_levy(monthly_salary)
            return levy_data['employee_contribution']
        else:
            # For other components, use legacy logic
            return _get_legacy_deduction_amount(component, deduction_item, monthly_salary, effective_date, formula_id)
            
    except Exception as e:
        print(f"Error calculating deduction amount: {e}")
        return Decimal('0')
def calculate_other_deduction(salary, title='', type='', effective_date=None, formula_id=None):
    """Calculate other deductions including housing levy"""
    try:
        formula_overrides = {}
        if formula_id:
            formula_overrides[type] = formula_id
        
        engine = PayrollCalculationEngine(effective_date or date.today(), formula_overrides)
        
        if 'housing' in title.lower() or 'levy' in title.lower():
            levy_data = engine.calculate_housing_levy(salary)
            return levy_data['relief'], levy_data['employee_contribution'], levy_data['employer_contribution']
        else:
            rates, applicable_relief, employee_percentage, employer_percentage = engine.load_formula_rates(type, title=title)
            
            relief = Decimal('0')
            employee_contribution = Decimal('0')
            employer_contribution = Decimal('0')
            
            rates = sorted(rates, key=lambda x: x[0])
            
            for lower, upper, rate in rates:
                if salary > lower:
                    taxable_amount = min(upper - lower, max(Decimal('0'), salary - lower))
                    total_contribution = taxable_amount * rate
                    
                    employee_contribution = total_contribution * employee_percentage
                    employer_contribution = total_contribution * employer_percentage
                    relief = applicable_relief * employee_contribution
                    break
            
            return relief, round(employee_contribution, 2), round(employer_contribution, 2)
        
    except Exception as e:
        print(f"Error calculating other deduction: {e}")
        return Decimal('0'), Decimal('0'), Decimal('0')

def calculate_nhif_contribution(salary, title='n.h.i.f', effective_date=None, formula_id=None):
    """Calculate NHIF contributions using legacy rates (pre-2025)"""
    try:
        formula_overrides = {}
        if formula_id:
            formula_overrides['nhif'] = formula_id
        
        engine = PayrollCalculationEngine(effective_date or date.today(), formula_overrides)
        nhif_data = engine.calculate_nhif_contribution(salary)
        
        return nhif_data['relief'], nhif_data['employee_contribution'], nhif_data['employer_contribution']
        
    except Exception as e:
        print(f"Error calculating NHIF contribution: {e}")
        return Decimal('0'), Decimal('0'), Decimal('0')

def calculate_shif_deduction(salary, title='s.h.i.f', effective_date=None, formula_id=None):
    """Calculate SHIF contributions using 2025 rates"""
    try:
        formula_overrides = {}
        if formula_id:
            formula_overrides['shif'] = formula_id
        
        engine = PayrollCalculationEngine(effective_date or date.today(), formula_overrides)
        shif_data = engine.calculate_shif_contribution(salary)
        
        return shif_data['relief'], shif_data['employee_contribution'], shif_data['employer_contribution']
        
    except Exception as e:
        print(f"Error calculating SHIF contribution: {e}")
        return Decimal('0'), Decimal('0'), Decimal('0')

def generate_random_code(prefix):
    """Generate random code for various purposes"""
    random_number = random.randint(1, 99999)
    formatted_number = f"{random_number:05}"
    return f"{prefix}{formatted_number}"

def get_fbt_amount(loan_amount, formula):
    """Calculate the Fringe Benefit Tax (FBT) based on the formula and loan amount"""
    try:
        engine = PayrollCalculationEngine(date.today(), {})
        rates, _, _, _ = engine.load_formula_rates('fbt', title='fringe_benefit_tax')
        
        fbt_amount = Decimal('0')
        rates = sorted(rates, key=lambda x: x[0])
        
        for lower, upper, rate in rates:
            if lower <= loan_amount <= upper:
                if rate < 1:
                    fbt_amount = loan_amount * rate
                else:
                    fbt_amount = rate
                break
        
        return fbt_amount
        
    except Exception as e:
        print(f"Error calculating FBT: {e}")
        return Decimal('0')

def calculate_interest(principal_amount, interest_rate, num_installments, formula):
    """Calculate the total interest based on the formula"""
    total_interest = interest = Decimal('0')
    if formula == "Fixed":
        total_interest = interest = principal_amount * interest_rate / Decimal('100') * num_installments / 12
        return total_interest, interest
    elif formula == "Reducing Balance":
        balance = principal_amount
        monthly_rate = interest_rate / Decimal('100') / Decimal('12')
        for _ in range(num_installments):
            interest = balance * monthly_rate
            total_interest += interest
            balance -= balance / num_installments
        return round(total_interest), round(interest)
    else:
        return Decimal('0'), Decimal('0')

def calculate_number_of_installments(principal_amount, monthly_installment, interest_rate, formula):
    """Calculate the number of installments needed to repay the loan"""
    if formula == "Fixed":
        total_repayment_amount = principal_amount + calculate_interest(principal_amount, interest_rate, 1, "Fixed")[0]
        return int(total_repayment_amount / monthly_installment)
    elif formula == "Reducing Balance":
        total_amount = principal_amount
        installments = 0
        while total_amount > 0:
            installments += 1
            interest = total_amount * (interest_rate / Decimal('100') / Decimal('12'))
            total_amount += interest
            total_amount -= monthly_installment
        return installments
    else:
        return 0

def get_loan_deduction(loan):
    """Deduct loan installments from employee's gross pay after tax, including interest and optional FBT"""
    total_deduction = Decimal('0')

    num_installments = calculate_number_of_installments(loan.principal_amount, loan.monthly_installment, loan.interest_rate, loan.interest_formula)
    total_interest, interest = calculate_interest(loan.principal_amount, loan.interest_rate, num_installments, loan.interest_formula)
    total_repayment_amount = loan.principal_amount + total_interest
    
    if loan.monthly_installment <= Decimal('0'):
        loan.monthly_installment = total_repayment_amount / num_installments
    
    remaining_amount = total_repayment_amount - loan.amount_repaid
    installment_to_deduct = min(remaining_amount, loan.monthly_installment)
    total_deduction += installment_to_deduct
    
    loan.amount_repaid += installment_to_deduct
    loan.interest_paid += interest
    loan.no_of_installments_paid += 1
    
    if loan.amount_repaid >= total_repayment_amount:
        loan.is_active = False
    loan.save()
    
    # Calculate FBT if applicable
    employer_fbt, employee_fbt = 0, 0
    if loan.fringe_benefit_tax:
        fbt_formula = loan.fringe_benefit_tax
        fbt_amount = get_fbt_amount(installment_to_deduct, fbt_formula)
        
        split_ratios = SplitRatio.objects.filter(formula=fbt_formula).first()
        if split_ratios:
            employer_percentage = split_ratios.employer_percentage / Decimal('100')
            employee_percentage = split_ratios.employee_percentage / Decimal('100')
            
            employer_fbt += fbt_amount * employer_percentage
            employee_fbt += fbt_amount * employee_percentage
        total_deduction += employee_fbt
    
    return total_deduction, interest