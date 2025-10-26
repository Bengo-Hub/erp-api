"""
P10A Employer Return Formatter Service

Modular components for generating KRA-compliant P10A reports with multi-tab support.
Each tab builder is a single-responsibility class for maintainability and reusability.

KRA Requirements:
- Tab B: Employee Details (annual summary)
- Tab C: Lump Sum Payments (if any)
- Tab D: FBT Details (Fringe Benefits Tax)
- Tab M: Housing Levy (New 07/2025)
"""

import polars as pl
from decimal import Decimal
from typing import Dict, List, Any, Optional
from django.db.models import Sum, Q
from django.utils import timezone
import logging

from hrm.employees.models import Employee
from hrm.payroll.models import Payslip

logger = logging.getLogger(__name__)


class EmployeeDetailsTab:
    """Tab B: Employee Details - Annual employee tax information."""
    
    TAB_KEY = 'B_Employee_Details'
    TITLE = 'B: Employee Details (KRA Form P10A - Simplified)'
    
    COLUMNS = [
        {'field': 'pin_of_employee', 'header': 'PIN of Employee'},
        {'field': 'name_of_employee', 'header': 'Name of Employee'},
        {'field': 'residential_status', 'header': 'Residential Status'},
        {'field': 'type_of_employment', 'header': 'Type of Employment'},
        {'field': 'person_with_disability', 'header': 'Person with Disability'},
        {'field': 'total_cash_pay', 'header': 'Total Cash Pay (KShs)'},
        {'field': 'type_of_housing', 'header': 'Type of Housing'},
        {'field': 'rent_of_house_provided', 'header': 'Rent of House Provided'},
        {'field': 'social_health_insurance_fund', 'header': 'SHIF Contribution'},
        {'field': 'actual_contribution_nssf', 'header': 'NSSF Contribution'},
        {'field': 'monthly_personal_relief', 'header': 'Monthly Personal Relief'},
        {'field': 'self_assessed_tax', 'header': 'Self Assessed Tax'},
    ]
    
    @staticmethod
    def build(payslips_qs) -> Dict[str, Any]:
        """
        Build Tab B data from payslips.
        
        Args:
            payslips_qs: QuerySet of payslips for the year
            
        Returns:
            Dict with data and metadata
        """
        employee_data = []
        
        for employee_id in payslips_qs.values_list('employee_id', flat=True).distinct():
            employee_payslips = payslips_qs.filter(employee_id=employee_id)
            employee = employee_payslips.first().employee
            
            # Aggregate annual totals
            aggregated = employee_payslips.aggregate(
                total_gross=Sum('gross_pay'),
                total_benefits=Sum('total_earnings'),
                total_nssf=Sum('nssf_employee_tier_1') + Sum('nssf_employee_tier_2'),
                total_taxable=Sum('taxable_pay'),
                total_tax_charged=Sum('paye'),
                total_reliefs=Sum('reliefs'),
                total_fbt=Sum('fringe_benefit_tax') if hasattr(Payslip, 'fringe_benefit_tax') else 0,
            )
            
            # Build employee detail row
            employee_row = {
                'pin_of_employee': employee.pin_no or 'N/A',
                'name_of_employee': employee.user.get_full_name(),
                'residential_status': EmployeeDetailsTab._get_residential_status(employee),
                'type_of_employment': EmployeeDetailsTab._get_employment_type(employee),
                'person_with_disability': EmployeeDetailsTab._get_disability_status(employee),
                'total_cash_pay': float(aggregated.get('total_gross') or 0),
                'type_of_housing': EmployeeDetailsTab._get_housing_type(aggregated),
                'rent_of_house_provided': 0.0,
                'social_health_insurance_fund': 0.0,  # SHIF contribution
                'actual_contribution_nssf': float(aggregated.get('total_nssf') or 0),
                'monthly_personal_relief': float(aggregated.get('total_reliefs', 0) or 0) / 12,
                'self_assessed_tax': 0.0,
            }
            
            employee_data.append(employee_row)
        
        df = pl.DataFrame(employee_data) if employee_data else pl.DataFrame([])
        
        return {
            'data': df.to_dicts() if not df.is_empty() else [],
            'columns': EmployeeDetailsTab.COLUMNS,
            'title': EmployeeDetailsTab.TITLE,
            'row_count': len(df)
        }
    
    @staticmethod
    def _get_residential_status(employee) -> str:
        """Get employee's residential status from profile."""
        if hasattr(employee, 'hr_details') and employee.hr_details:
            return employee.hr_details.residential_status or 'Resident'
        return 'Resident'
    
    @staticmethod
    def _get_employment_type(employee) -> str:
        """Get employment type from employee profile."""
        if hasattr(employee, 'hr_details') and employee.hr_details:
            return employee.hr_details.employment_type or 'Permanent'
        return 'Permanent'
    
    @staticmethod
    def _get_disability_status(employee) -> str:
        """Get disability status from employee profile."""
        if hasattr(employee, 'hr_details') and employee.hr_details:
            is_disabled = employee.hr_details.person_with_disability if hasattr(employee.hr_details, 'person_with_disability') else False
            return 'Yes' if is_disabled else 'No'
        return 'No'
    
    @staticmethod
    def _get_housing_type(aggregated: Dict) -> str:
        """Determine housing type based on salary level."""
        total_pay = float(aggregated.get('total_gross', 0) or 0)
        return 'Employer Owned House' if total_pay > 100000 else 'Private'


class FBTDetailsTab:
    """Tab D: Fringe Benefits Tax - Employee loan and FBT details."""
    
    TAB_KEY = 'D_FBT_Details'
    TITLE = 'D: FBT Details (Fringe Benefits Tax - KRA Required)'
    
    COLUMNS = [
        {'field': 'pin_of_employee', 'header': 'PIN of Employee'},
        {'field': 'name_of_employee', 'header': 'Name of Employee'},
        {'field': 'loan_account_number', 'header': 'Loan Account Number'},
        {'field': 'loan_amount', 'header': 'Loan Amount (KShs)'},
        {'field': 'amount_of_loan_outstanding', 'header': 'Outstanding Loan (KShs)'},
        {'field': 'rate_of_interest_on_loan', 'header': 'Interest Rate (%)'},
        {'field': 'interest_on_loan', 'header': 'Interest on Loan (KShs)'},
        {'field': 'prescribed_market_rate', 'header': 'Prescribed Market Rate (%)'},
        {'field': 'amount_of_fringe_benefit', 'header': 'Fringe Benefit (KShs)'},
    ]
    
    @staticmethod
    def build(payslips_qs) -> Dict[str, Any]:
        """
        Build Tab D data (FBT) from payslips.
        Only includes employees with FBT or loans.
        
        Args:
            payslips_qs: QuerySet of payslips for the year
            
        Returns:
            Dict with data and metadata
        """
        fbt_data = []
        
        for employee_id in payslips_qs.values_list('employee_id', flat=True).distinct():
            employee_payslips = payslips_qs.filter(employee_id=employee_id)
            employee = employee_payslips.first().employee
            
            aggregated = employee_payslips.aggregate(
                total_fbt=Sum('fringe_benefit_tax') if hasattr(Payslip, 'fringe_benefit_tax') else 0,
            )
            
            fbt_amount = float(aggregated.get('total_fbt', 0) or 0)
            
            # Only include if FBT or loans exist
            if fbt_amount > 0 or FBTDetailsTab._has_loans(employee):
                fbt_row = {
                    'pin_of_employee': employee.pin_no or 'N/A',
                    'name_of_employee': employee.user.get_full_name(),
                    'loan_account_number': FBTDetailsTab._get_loan_account(employee),
                    'loan_amount': FBTDetailsTab._get_loan_amount(employee),
                    'amount_of_loan_outstanding': FBTDetailsTab._get_outstanding_loan(employee),
                    'rate_of_interest_on_loan': FBTDetailsTab._get_loan_interest_rate(),
                    'interest_on_loan': FBTDetailsTab._get_loan_interest(employee),
                    'prescribed_market_rate': FBTDetailsTab._get_prescribed_rate(),
                    'amount_of_fringe_benefit': fbt_amount,
                }
                fbt_data.append(fbt_row)
        
        df = pl.DataFrame(fbt_data) if fbt_data else pl.DataFrame([])
        
        return {
            'data': df.to_dicts() if not df.is_empty() else [],
            'columns': FBTDetailsTab.COLUMNS,
            'title': FBTDetailsTab.TITLE,
            'row_count': len(df)
        }
    
    @staticmethod
    def _has_loans(employee) -> bool:
        """Check if employee has any loans."""
        try:
            if hasattr(employee, 'employeeloans_set'):
                return employee.employeeloans_set.filter(status='active').exists()
        except Exception:
            pass
        return False
    
    @staticmethod
    def _get_loan_account(employee) -> str:
        """Get employee's loan account number."""
        try:
            if hasattr(employee, 'employeeloans_set'):
                loan = employee.employeeloans_set.filter(status='active').first()
                if loan:
                    return str(loan.id)
        except Exception:
            pass
        return ''
    
    @staticmethod
    def _get_loan_amount(employee) -> float:
        """Get total loan amount."""
        try:
            if hasattr(employee, 'employeeloans_set'):
                total = employee.employeeloans_set.filter(status='active').aggregate(total=Sum('amount'))
                return float(total.get('total', 0) or 0)
        except Exception:
            pass
        return 0.0
    
    @staticmethod
    def _get_outstanding_loan(employee) -> float:
        """Get outstanding loan balance."""
        try:
            if hasattr(employee, 'employeeloans_set'):
                total = employee.employeeloans_set.filter(status='active').aggregate(balance=Sum('balance'))
                return float(total.get('balance', 0) or 0)
        except Exception:
            pass
        return 0.0
    
    @staticmethod
    def _get_loan_interest_rate() -> float:
        """Get KRA prescribed loan interest rate."""
        return 3.5  # KRA standard rate (update from config if needed)
    
    @staticmethod
    def _get_loan_interest(employee) -> float:
        """Calculate interest on employee loans."""
        try:
            if hasattr(employee, 'employeeloans_set'):
                total = employee.employeeloans_set.filter(status='active').aggregate(interest=Sum('interest_paid'))
                return float(total.get('interest', 0) or 0)
        except Exception:
            pass
        return 0.0
    
    @staticmethod
    def _get_prescribed_rate() -> float:
        """Get KRA prescribed market rate for valuing benefits."""
        return 8.5  # KRA standard rate (update from config if needed)


class HousingLevyTab:
    """Tab M: Housing Levy - New KRA requirement from 07/2025."""
    
    TAB_KEY = 'M_Housing_Levy_Details'
    TITLE = 'M: Housing Levy Details (New 07/2025 - KRA Required)'
    
    COLUMNS = [
        {'field': 'pin_of_employee', 'header': 'PIN of Employee'},
        {'field': 'name_of_employee', 'header': 'Name of Employee'},
        {'field': 'housing_levy_rate', 'header': 'Levy Rate (%)'},
        {'field': 'total_cash_pay_for_levy', 'header': 'Total Cash Pay (KShs)'},
        {'field': 'housing_levy_amount', 'header': 'Housing Levy Paid (KShs)'},
    ]
    
    # KRA Standard housing levy rate
    LEVY_RATE = 1.5  # 1.5% as per KRA
    
    @staticmethod
    def build(payslips_qs) -> Dict[str, Any]:
        """
        Build Tab M data (Housing Levy) from payslips.
        Only includes employees with housing levy contributions.
        
        Args:
            payslips_qs: QuerySet of payslips for the year
            
        Returns:
            Dict with data and metadata
        """
        housing_data = []
        
        for employee_id in payslips_qs.values_list('employee_id', flat=True).distinct():
            employee_payslips = payslips_qs.filter(employee_id=employee_id)
            employee = employee_payslips.first().employee
            
            aggregated = employee_payslips.aggregate(
                total_gross=Sum('gross_pay'),
                total_levy=Sum('housing_levy') if hasattr(Payslip, 'housing_levy') else 0,
            )
            
            levy_amount = float(aggregated.get('total_levy', 0) or 0)
            
            # Only include if housing levy exists
            if levy_amount > 0:
                housing_row = {
                    'pin_of_employee': employee.pin_no or 'N/A',
                    'name_of_employee': employee.user.get_full_name(),
                    'housing_levy_rate': HousingLevyTab.LEVY_RATE,
                    'total_cash_pay_for_levy': float(aggregated.get('total_gross', 0) or 0),
                    'housing_levy_amount': levy_amount,
                }
                housing_data.append(housing_row)
        
        df = pl.DataFrame(housing_data) if housing_data else pl.DataFrame([])
        
        return {
            'data': df.to_dicts() if not df.is_empty() else [],
            'columns': HousingLevyTab.COLUMNS,
            'title': HousingLevyTab.TITLE,
            'row_count': len(df)
        }


class LumpSumTab:
    """Tab C: Lump Sum Payments - Gratuity and severance payments."""
    
    TAB_KEY = 'C_Lump_Sum_Payments'
    TITLE = 'C: Lump Sum Payments (Gratuity, Severance, etc.)'
    
    COLUMNS = [
        {'field': 'pin_of_employee', 'header': 'PIN of Employee'},
        {'field': 'name_of_employee', 'header': 'Name of Employee'},
        {'field': 'payment_type', 'header': 'Payment Type'},
        {'field': 'payment_amount', 'header': 'Amount (KShs)'},
        {'field': 'payment_date', 'header': 'Payment Date'},
    ]
    
    @staticmethod
    def build(payslips_qs) -> Dict[str, Any]:
        """
        Build Tab C data (Lump Sum) from payslips or separate model.
        
        Args:
            payslips_qs: QuerySet of payslips for the year
            
        Returns:
            Dict with data and metadata
        """
        lump_sum_data = []
        
        # TODO: Query lump sum payments from appropriate model
        # This is a placeholder for integration with severance/gratuity records
        
        df = pl.DataFrame(lump_sum_data) if lump_sum_data else pl.DataFrame([])
        
        return {
            'data': df.to_dicts() if not df.is_empty() else [],
            'columns': LumpSumTab.COLUMNS,
            'title': LumpSumTab.TITLE,
            'row_count': len(df)
        }


class P10AFormatter:
    """Main P10A Report Formatter - Orchestrates all tabs."""
    
    # Map tab builders
    TAB_BUILDERS = {
        'B': EmployeeDetailsTab,
        'C': LumpSumTab,
        'D': FBTDetailsTab,
        'M': HousingLevyTab,
    }
    
    @staticmethod
    def format(payslips_qs, year: int, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format complete P10A report with all tabs.
        
        Args:
            payslips_qs: QuerySet of payslips for the year
            year: Tax year
            filters: Applied filters
            
        Returns:
            Dict with tabs and metadata
        """
        if not payslips_qs.exists():
            return {
                'report_type': 'P10A',
                'tabs': {},
                'message': 'No data found for the specified filters',
                'year': year,
                'totals': {'total_employees': 0},
            }
        
        tabs = {}
        total_employees = 0
        total_gross = 0.0
        
        # Build Tab B (Employee Details) - always present if data exists
        try:
            tab_b_data = EmployeeDetailsTab.build(payslips_qs)
            tabs[EmployeeDetailsTab.TAB_KEY] = tab_b_data
            total_employees = tab_b_data.get('row_count', 0)
            if tab_b_data.get('data'):
                total_gross = sum(row.get('total_cash_pay', 0) for row in tab_b_data['data'])
        except Exception as e:
            logger.error(f"Error building Tab B: {str(e)}")
        
        # Build Tab D (FBT) - if applicable
        try:
            tab_d_data = FBTDetailsTab.build(payslips_qs)
            if tab_d_data.get('row_count', 0) > 0:
                tabs[FBTDetailsTab.TAB_KEY] = tab_d_data
        except Exception as e:
            logger.error(f"Error building Tab D: {str(e)}")
        
        # Build Tab M (Housing Levy) - if applicable
        try:
            tab_m_data = HousingLevyTab.build(payslips_qs)
            if tab_m_data.get('row_count', 0) > 0:
                tabs[HousingLevyTab.TAB_KEY] = tab_m_data
        except Exception as e:
            logger.error(f"Error building Tab M: {str(e)}")
        
        # Build Tab C (Lump Sum) - if applicable
        try:
            tab_c_data = LumpSumTab.build(payslips_qs)
            if tab_c_data.get('row_count', 0) > 0:
                tabs[LumpSumTab.TAB_KEY] = tab_c_data
        except Exception as e:
            logger.error(f"Error building Tab C: {str(e)}")
        
        return {
            'report_type': 'P10A',
            'format': 'simplified',  # New KRA format from 07/2025
            'title': f'P10A Employer Return of Employees - {year} (KRA Simplified Format)',
            'tabs': tabs,
            'totals': {
                'total_employees': total_employees,
                'total_gross_pay': total_gross,
                'tabs_included': list(tabs.keys()),
            },
            'year': year,
            'filters_applied': filters,
            'generated_at': timezone.now().isoformat(),
            'kra_compliance': {
                'format_version': '07/2025',
                'tabs_required': ['B'],
                'tabs_conditional': ['C', 'D', 'M'],
                'notes': 'Tab M (Housing Levy) is new requirement from 07/2025'
            }
        }
