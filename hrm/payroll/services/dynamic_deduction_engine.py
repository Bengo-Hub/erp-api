"""
Dynamic Deduction Engine Service
Handles flexible deduction ordering based on formula versions and payroll dates
"""

from datetime import date
from decimal import Decimal
from django.db.models import Q
from hrm.payroll_settings.models import (
    Formulas, FormulaItems, PayrollComponents, 
    SplitRatio, Relief
)
from .core_calculations import PayrollCalculationEngine


class DynamicDeductionEngine:
    """
    Engine for calculating deductions in the order specified by formula versions
    """
    
    def __init__(self, formula_version, payroll_date, formula_overrides=None):
        self.formula_version = formula_version
        self.payroll_date = payroll_date
        self.formula_overrides = formula_overrides or {}
        self.deduction_order = self._load_deduction_order()
        self.calculation_engine = PayrollCalculationEngine(payroll_date, formula_overrides)
    
    def _load_deduction_order(self):
        """Load deduction order from the formula version"""
        try:
            formula = Formulas.objects.filter(
                version=self.formula_version,
                is_current=True
            ).first()
            
            if formula and formula.deduction_order:
                return formula.deduction_order
            
            return self._get_default_deduction_order()
            
        except Exception as e:
            print(f"Error loading deduction order: {e}")
            return self._get_default_deduction_order()
    
    def _get_default_deduction_order(self):
        """Default deduction order for backward compatibility"""
        return [
            {"phase": "before_tax", "components": ["nssf", "shif", "housing_levy"]},
            {"phase": "after_tax", "components": ["paye"]},
            {"phase": "after_paye", "components": ["loans", "advances", "loss_damages"]},
            {"phase": "final", "components": ["non_cash_benefits"]}
        ]
    
    def calculate_deductions_in_order(self, gross_pay, employee, payment_period, formula_overrides=None):
        """
        Calculate deductions in the order specified by the formula version
        """
        deductions = {
            'before_tax': {},
            'after_tax': {},
            'after_paye': {},
            'final': {}
        }
        
        # Calculate deductions for each phase in order
        for phase_config in self.deduction_order:
            phase_name = phase_config['phase']
            components = phase_config['components']
            
            for component in components:
                if component == 'nssf':
                    nssf_data = self._calculate_nssf(gross_pay, payment_period, formula_overrides)
                    deductions[phase_name]['nssf'] = {
                        'amount': nssf_data.get('total_employee', Decimal('0')),
                        'tier_1_employee': nssf_data.get('tier_1_employee', Decimal('0')),
                        'tier_2_employee': nssf_data.get('tier_2_employee', Decimal('0')),
                        'employer_contribution': nssf_data.get('total_employer', Decimal('0'))
                    }
                elif component == 'shif':
                    shif_data = self._calculate_shif(gross_pay, payment_period, formula_overrides)
                    deductions[phase_name]['shif'] = {
                        'amount': shif_data.get('employee_contribution', Decimal('0')),
                        'employee_contribution': shif_data.get('employee_contribution', Decimal('0')),
                        'employer_contribution': shif_data.get('employer_contribution', Decimal('0')),
                        'relief': shif_data.get('relief', Decimal('0'))
                    }
                elif component == 'housing_levy':
                    levy_data = self._calculate_housing_levy(gross_pay, payment_period, formula_overrides)
                    deductions[phase_name]['housing_levy'] = {
                        'amount': levy_data.get('employee_contribution', Decimal('0')),
                        'employee_contribution': levy_data.get('employee_contribution', Decimal('0')),
                        'employer_contribution': levy_data.get('employer_contribution', Decimal('0')),
                        'relief': levy_data.get('relief', Decimal('0'))
                    }
                elif component == 'paye':
                    taxable_income = self._calculate_taxable_income(gross_pay, deductions['before_tax'])
                    paye_data = self._calculate_paye(taxable_income, employee, payment_period, formula_overrides)
                    deductions[phase_name]['paye'] = {
                        'amount': paye_data.get('amount', Decimal('0')),
                        'personal_relief': paye_data.get('personal_relief', Decimal('0'))
                    }
                elif component == 'loans':
                    loans_data = self._calculate_loans(employee, gross_pay)
                    deductions[phase_name]['loans'] = {
                        'amount': loans_data.get('amount', Decimal('0'))
                    }
                elif component == 'advances':
                    advances_data = self._calculate_advances(employee, payment_period, gross_pay)
                    deductions[phase_name]['advances'] = {
                        'amount': advances_data.get('amount', Decimal('0'))
                    }
                elif component == 'loss_damages':
                    loss_data = self._calculate_loss_damages(employee, payment_period, gross_pay)
                    deductions[phase_name]['loss_damages'] = {
                        'amount': loss_data.get('amount', Decimal('0'))
                    }
                elif component == 'non_cash_benefits':
                    benefits_data = self._calculate_non_cash_benefits(employee, gross_pay)
                    deductions[phase_name]['non_cash_benefits'] = {
                        'amount': benefits_data.get('amount', Decimal('0'))
                    }
        
        return deductions
    
    def _calculate_nssf(self, gross_pay, payment_period, formula_overrides):
        """Calculate NSSF contributions using centralized engine"""
        try:
            formula_id = formula_overrides.get('nssf') if formula_overrides else None
            nssf_data = self.calculation_engine.calculate_nssf_contribution(gross_pay)
            return nssf_data
        except Exception as e:
            print(f"Error calculating NSSF: {e}")
            return {
                'tier_1_employee': Decimal('0'), 
                'tier_2_employee': Decimal('0'), 
                'total_employer': Decimal('0'),
                'total_employee': Decimal('0')
            }
    
    def _calculate_shif(self, gross_pay, payment_period, formula_overrides):
        """Calculate SHIF contributions using centralized engine"""
        try:
            formula_id = formula_overrides.get('shif') if formula_overrides else None
            shif_data = self.calculation_engine.calculate_shif_contribution(gross_pay)
            return shif_data
        except Exception as e:
            print(f"Error calculating SHIF: {e}")
            return {
                'employee_contribution': Decimal('0'), 
                'employer_contribution': Decimal('0'), 
                'relief': Decimal('0')
            }
    
    def _calculate_housing_levy(self, gross_pay, payment_period, formula_overrides):
        """Calculate Housing Levy using centralized engine"""
        try:
            formula_id = formula_overrides.get('levy') if formula_overrides else None
            levy_data = self.calculation_engine.calculate_housing_levy(gross_pay)
            return levy_data
        except Exception as e:
            print(f"Error calculating Housing Levy: {e}")
            return {
                'employee_contribution': Decimal('0'), 
                'employer_contribution': Decimal('0'), 
                'relief': Decimal('0')
            }
    
    def _calculate_taxable_income(self, gross_pay, before_tax_deductions):
        """Calculate taxable income after before-tax deductions"""
        total_before_tax = Decimal('0')
        for component, details in before_tax_deductions.items():
            if component == 'nssf':
                total_before_tax += details.get('amount', Decimal('0'))
            elif component == 'shif':
                total_before_tax += details.get('amount', Decimal('0'))
            elif component == 'housing_levy':
                total_before_tax += details.get('amount', Decimal('0'))
        
        return gross_pay - total_before_tax
    
    def _calculate_paye(self, taxable_income, employee, payment_period, formula_overrides):
        """Calculate PAYE tax using centralized engine"""
        try:
            formula_id = formula_overrides.get('income') if formula_overrides else None
            salary_details = employee.salary_details.first()
            
            if salary_details and salary_details.income_tax == "primary":
                paye = self.calculation_engine.calculate_income_tax(taxable_income, "primary")
                return {
                    'amount': paye,
                    'personal_relief': Decimal('2400')
                }
            elif salary_details and salary_details.income_tax == "secondary":
                return {
                    'amount': taxable_income,
                    'personal_relief': Decimal('0')
                }
            else:
                return {
                    'amount': Decimal('0'),
                    'personal_relief': Decimal('0')
                }
        except Exception as e:
            print(f"Error calculating PAYE: {e}")
            return {
                'amount': Decimal('0'),
                'personal_relief': Decimal('0')
            }
    
    def _calculate_loans(self, employee, gross_pay):
        """Calculate loan deductions using centralized engine"""
        try:
            deductions = self.calculation_engine.calculate_employee_deductions(employee, gross_pay)
            return {'amount': deductions.get('loans', Decimal('0'))}
        except Exception as e:
            print(f"Error calculating loans: {e}")
            return {'amount': Decimal('0')}
    
    def _calculate_advances(self, employee, payment_period, gross_pay):
        """Calculate advance deductions using centralized engine"""
        try:
            deductions = self.calculation_engine.calculate_employee_deductions(employee, gross_pay)
            return {'amount': deductions.get('advances', Decimal('0'))}
        except Exception as e:
            print(f"Error calculating advances: {e}")
            return {'amount': Decimal('0')}
    
    def _calculate_loss_damages(self, employee, payment_period, gross_pay):
        """Calculate loss and damage deductions using centralized engine"""
        try:
            deductions = self.calculation_engine.calculate_employee_deductions(employee, gross_pay)
            return {'amount': deductions.get('loss_damages', Decimal('0'))}
        except Exception as e:
            print(f"Error calculating loss/damages: {e}")
            return {'amount': Decimal('0')}
    
    def _calculate_non_cash_benefits(self, employee, gross_pay):
        """Calculate non-cash benefit deductions using centralized engine"""
        try:
            deductions = self.calculation_engine.calculate_employee_deductions(employee, gross_pay)
            return {'amount': deductions.get('non_cash_benefits', Decimal('0'))}
        except Exception as e:
            print(f"Error calculating non-cash benefits: {e}")
            return {'amount': Decimal('0')}
    
    def get_deduction_summary(self, deductions):
        """Get a summary of all deductions organized by phase"""
        summary = {
            'total_before_tax': Decimal('0'),
            'total_after_tax': Decimal('0'),
            'total_after_paye': Decimal('0'),
            'total_final': Decimal('0'),
            'breakdown': {}
        }
        
        for phase, phase_deductions in deductions.items():
            phase_total = Decimal('0')
            for component, data in phase_deductions.items():
                if isinstance(data, dict):
                    amount = data.get('amount', Decimal('0'))
                    phase_total += amount
                    summary['breakdown'][f"{phase}_{component}"] = amount
            
            summary[f'total_{phase}'] = phase_total
        
        return summary