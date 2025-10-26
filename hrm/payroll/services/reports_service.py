"""
Payroll Reports Service using Polars for high-performance, flexible report generation.

This service generates statutory and operational reports including:
- P9 Tax Deduction Cards
- P10A Employer Return of Employees (KRA-compliant multi-format)
- Withholding Tax Reports
- NSSF/NHIF/NITA Statutory Deduction Reports
- Bank Net Pay Reports
- Muster Roll Reports with dynamic columns
"""

import polars as pl
from decimal import Decimal
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from django.db.models import Q, Sum, Avg, Count
from django.utils import timezone
import logging

from hrm.payroll.models import Payslip
from hrm.employees.models import Employee, EmployeeBankAccount
from business.models import Branch
from .p10a_formatter import P10AFormatter

logger = logging.getLogger(__name__)


class PayrollReportsService:
    """
    Service for generating flexible payroll reports using Polars.
    All reports support dynamic filtering and flexible column structures.
    """
    
    def __init__(self):
        self.default_filters = {}
    
    def generate_p9_report(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate P9 Tax Deduction Card report (Employee tax statement).
        
        Filters:
        - payment_period: Date or period (YYYY-MM)
        - year: Tax year (YYYY)
        - employee_ids: List of employee IDs
        - department_ids: List of department IDs
        - branch_id: Branch ID
        """
        try:
            # Build queryset with filters
            payslips_qs = self._build_payslip_queryset(filters)
            
            if not payslips_qs.exists():
                return {
                    'report_type': 'P9',
                    'data': [],
                    'columns': [],
                    'message': 'No data found for the specified filters'
                }
            
            # Extract data for Polars processing
            data = []
            for payslip in payslips_qs.select_related('employee', 'employee__user', 'employee__hr_details', 'employee__hr_details__department'):
                employee = payslip.employee
                data.append({
                    'employee_id': employee.id,
                    'employee_number': employee.user.username,
                    'employee_name': employee.user.get_full_name(),
                    'pin_number': employee.pin_no,
                    'month': payslip.payment_period.strftime('%B %Y') if payslip.payment_period else '',
                    'basic_salary': float(payslip.gross_pay or 0),
                    'benefits_allowances': float(payslip.total_earnings or 0) - float(payslip.gross_pay or 0),
                    'gross_pay': float(payslip.gross_pay or 0),
                    'defined_contribution_pension': float(payslip.nssf_employee_tier_1 or 0) + float(payslip.nssf_employee_tier_2 or 0),
                    'owner_occupied_interest': 0.0,  # Would need additional data
                    'retirement_contribution_owner': 0.0,  # Would need additional data
                    'chargeable_pay': float(payslip.taxable_pay or 0),
                    'tax_charged': float(payslip.paye or 0),
                    'personal_relief': float(payslip.tax_relief or 0),
                    'insurance_relief': float(payslip.reliefs or 0) - float(payslip.tax_relief or 0),
                    'paye_tax': float(payslip.paye or 0) - float(payslip.reliefs or 0),
                    'department': employee.hr_details.department.name if hasattr(employee, 'hr_details') and employee.hr_details and employee.hr_details.department else 'N/A',
                })
            
            # Create Polars DataFrame for processing
            df = pl.DataFrame(data)
            
            # Dynamic column definitions
            columns = [
                {'field': 'employee_number', 'header': 'Employee No.'},
                {'field': 'employee_name', 'header': 'Employee Name'},
                {'field': 'pin_number', 'header': 'PIN Number'},
                {'field': 'month', 'header': 'Month'},
                {'field': 'basic_salary', 'header': 'Basic Salary'},
                {'field': 'benefits_allowances', 'header': 'Benefits & Allowances'},
                {'field': 'gross_pay', 'header': 'Gross Pay'},
                {'field': 'defined_contribution_pension', 'header': 'Defined Contribution (NSSF)'},
                {'field': 'owner_occupied_interest', 'header': 'Owner Occupied Interest'},
                {'field': 'retirement_contribution_owner', 'header': 'Retirement Contribution'},
                {'field': 'chargeable_pay', 'header': 'Chargeable Pay'},
                {'field': 'tax_charged', 'header': 'Tax Charged'},
                {'field': 'personal_relief', 'header': 'Personal Relief'},
                {'field': 'insurance_relief', 'header': 'Insurance Relief'},
                {'field': 'paye_tax', 'header': 'PAYE'},
                {'field': 'department', 'header': 'Department'},
            ]
            
            # Calculate totals
            totals = {
                'total_gross_pay': float(df['gross_pay'].sum()),
                'total_chargeable_pay': float(df['chargeable_pay'].sum()),
                'total_tax_charged': float(df['tax_charged'].sum()),
                'total_paye': float(df['paye_tax'].sum()),
                'employee_count': len(df),
            }
            
            return {
                'report_type': 'P9',
                'title': 'P9 Tax Deduction Card',
                'data': df.to_dicts(),
                'columns': columns,
                'totals': totals,
                'filters_applied': filters,
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Error generating P9 report: {str(e)}")
            return {
                'report_type': 'P9',
                'error': str(e),
                'data': [],
                'columns': [],
            }
    
    def generate_p10a_report(self, filters: Dict[str, Any], format_type: str = 'simplified') -> Dict[str, Any]:
        """
        Generate P10A Employer Return of Employees with KRA-compliant multi-tab format.
        
        Delegates to P10AFormatter for modular, maintainable tab generation.
        
        Args:
            filters: Report filters (year, employee_ids, department_ids, branch_id)
            format_type: 'simplified' (new 07/2025, default), 'detailed', or 'legacy'
        
        Returns:
            Dict with tabs: B_Employee_Details, C_Lump_Sum, D_FBT, M_Housing_Levy
            Each tab includes data, columns, and metadata
        """
        try:
            year = filters.get('year')
            if not year:
                return {
                    'report_type': 'P10A',
                    'error': 'Year parameter is required for P10A report',
                    'tabs': {},
                }
            
            # Build queryset for entire year
            payslips_qs = Payslip.objects.filter(
                payment_period__year=year,
                delete_status=False
            )
            
            # Apply additional filters
            payslips_qs = self._apply_filters(payslips_qs, filters)
            
            # Use P10AFormatter to generate tabs
            return P10AFormatter.format(payslips_qs, year, filters)
            
        except Exception as e:
            logger.error(f"Error generating P10A report: {str(e)}", exc_info=True)
            return {
                'report_type': 'P10A',
                'error': str(e),
                'tabs': {},
            }
    
    def generate_statutory_deductions_report(self, filters: Dict[str, Any], deduction_type: str = 'nssf') -> Dict[str, Any]:
        """
        Generate statutory deductions reports (NSSF, NHIF/SHIF, NITA).
        
        Args:
            filters: Report filters (payment_period, year, employee_ids, etc.)
            deduction_type: 'nssf', 'nhif', 'shif', or 'nita'
        """
        try:
            payslips_qs = self._build_payslip_queryset(filters)
            
            if not payslips_qs.exists():
                return {
                    'report_type': deduction_type.upper(),
                    'data': [],
                    'columns': [],
                    'message': 'No data found for the specified filters'
                }
            
            # Extract data based on deduction type
            data = []
            for payslip in payslips_qs.select_related('employee', 'employee__user', 'employee__hr_details'):
                employee = payslip.employee
                
                if deduction_type == 'nssf':
                    employee_contribution = float(payslip.nssf_employee_tier_1 or 0) + float(payslip.nssf_employee_tier_2 or 0)
                    employer_contribution = float(payslip.nssf_employer_contribution or 0)
                    total_contribution = employee_contribution + employer_contribution
                    member_number = employee.nssf_no
                elif deduction_type in ['nhif', 'shif']:
                    employee_contribution = float(payslip.shif_or_nhif_contribution or 0)
                    employer_contribution = 0.0  # NHIF/SHIF is employee-only
                    total_contribution = employee_contribution
                    member_number = employee.shif_or_nhif_number or 'N/A'
                elif deduction_type == 'nita':
                    # NITA is 0.5% of gross pay (employer contribution)
                    employee_contribution = 0.0
                    employer_contribution = float(payslip.gross_pay or 0) * 0.005
                    total_contribution = employer_contribution
                    member_number = 'N/A'
                else:
                    continue
                
                data.append({
                    'employee_number': employee.user.username,
                    'employee_name': employee.user.get_full_name(),
                    'member_number': member_number,
                    'pin_number': employee.pin_no,
                    'month': payslip.payment_period.strftime('%B %Y') if payslip.payment_period else '',
                    'gross_pay': float(payslip.gross_pay or 0),
                    'employee_contribution': employee_contribution,
                    'employer_contribution': employer_contribution,
                    'total_contribution': total_contribution,
                    'department': employee.hr_details.department.name if hasattr(employee, 'hr_details') and employee.hr_details and employee.hr_details.department else 'N/A',
                })
            
            # Create Polars DataFrame
            df = pl.DataFrame(data)
            
            # Dynamic columns based on deduction type
            columns = [
                {'field': 'employee_number', 'header': 'Employee No.'},
                {'field': 'employee_name', 'header': 'Employee Name'},
                {'field': 'member_number', 'header': f'{deduction_type.upper()} Number'},
                {'field': 'pin_number', 'header': 'PIN Number'},
                {'field': 'month', 'header': 'Month'},
                {'field': 'gross_pay', 'header': 'Gross Pay'},
                {'field': 'employee_contribution', 'header': 'Employee Contribution'},
                {'field': 'employer_contribution', 'header': 'Employer Contribution'},
                {'field': 'total_contribution', 'header': 'Total Contribution'},
                {'field': 'department', 'header': 'Department'},
            ]
            
            # Calculate totals
            totals = {
                'total_employees': len(df),
                'total_gross_pay': float(df['gross_pay'].sum()),
                'total_employee_contribution': float(df['employee_contribution'].sum()),
                'total_employer_contribution': float(df['employer_contribution'].sum()),
                'total_contribution': float(df['total_contribution'].sum()),
            }
            
            return {
                'report_type': deduction_type.upper(),
                'title': f'{deduction_type.upper()} Statutory Deductions Report',
                'data': df.to_dicts(),
                'columns': columns,
                'totals': totals,
                'filters_applied': filters,
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Error generating {deduction_type.upper()} report: {str(e)}")
            return {
                'report_type': deduction_type.upper(),
                'error': str(e),
                'data': [],
                'columns': [],
            }
    
    def generate_bank_net_pay_report(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate Bank Net Pay report grouped by bank institution.
        Shows net pay amounts grouped by employee banks for payment processing.
        """
        try:
            payslips_qs = self._build_payslip_queryset(filters)
            
            if not payslips_qs.exists():
                return {
                    'report_type': 'BANK_NET_PAY',
                    'data': [],
                    'columns': [],
                    'message': 'No data found for the specified filters'
                }
            
            # Extract data with bank account information
            data = []
            for payslip in payslips_qs.select_related('employee', 'employee__user'):
                employee = payslip.employee
                
                # Get primary bank account
                bank_account = EmployeeBankAccount.objects.filter(
                    employee=employee,
                    is_primary=True,
                    status='active'
                ).select_related('bank_institution', 'bank_branch').first()
                
                if not bank_account:
                    # Get any active bank account
                    bank_account = EmployeeBankAccount.objects.filter(
                        employee=employee,
                        status='active'
                    ).select_related('bank_institution', 'bank_branch').first()
                
                bank_name = bank_account.bank_institution.name if bank_account else 'No Bank Account'
                bank_branch = bank_account.bank_branch.name if bank_account and bank_account.bank_branch else 'N/A'
                account_number = bank_account.account_number if bank_account else 'N/A'
                
                data.append({
                    'bank_name': bank_name,
                    'bank_branch': bank_branch,
                    'employee_number': employee.user.username,
                    'employee_name': employee.user.get_full_name(),
                    'account_number': account_number,
                    'month': payslip.payment_period.strftime('%B %Y') if payslip.payment_period else '',
                    'gross_pay': float(payslip.gross_pay or 0),
                    'total_deductions': float(payslip.gross_pay or 0) - float(payslip.net_pay or 0),
                    'net_pay': float(payslip.net_pay or 0),
                })
            
            # Create Polars DataFrame
            df = pl.DataFrame(data)
            
            # Group by bank and sort
            df = df.sort(['bank_name', 'employee_name'])
            
            # Dynamic columns
            columns = [
                {'field': 'bank_name', 'header': 'Bank Name'},
                {'field': 'bank_branch', 'header': 'Branch'},
                {'field': 'employee_number', 'header': 'Employee No.'},
                {'field': 'employee_name', 'header': 'Employee Name'},
                {'field': 'account_number', 'header': 'Account Number'},
                {'field': 'month', 'header': 'Month'},
                {'field': 'gross_pay', 'header': 'Gross Pay'},
                {'field': 'total_deductions', 'header': 'Total Deductions'},
                {'field': 'net_pay', 'header': 'Net Pay'},
            ]
            
            # Calculate totals by bank
            bank_totals = df.group_by('bank_name').agg([
                pl.col('net_pay').sum().alias('total_net_pay'),
                pl.col('employee_number').count().alias('employee_count')
            ]).to_dicts()
            
            # Calculate grand totals
            totals = {
                'total_employees': len(df),
                'total_gross_pay': float(df['gross_pay'].sum()),
                'total_deductions': float(df['total_deductions'].sum()),
                'total_net_pay': float(df['net_pay'].sum()),
                'banks': bank_totals,
            }
            
            return {
                'report_type': 'BANK_NET_PAY',
                'title': 'Bank Net Pay Report',
                'data': df.to_dicts(),
                'columns': columns,
                'totals': totals,
                'filters_applied': filters,
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Error generating Bank Net Pay report: {str(e)}")
            return {
                'report_type': 'BANK_NET_PAY',
                'error': str(e),
                'data': [],
                'columns': [],
            }
    
    def generate_muster_roll_report(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate Muster Roll report with flexible columns based on available data.
        This report includes all payroll components and is highly flexible.
        
        Filters:
        - payment_period: Date or period (YYYY-MM)
        - employee_ids: List of employee IDs
        - department_ids: List of department IDs
        - branch_id: Branch ID
        - include_components: List of component names to include (earnings, deductions, etc.)
        """
        try:
            payslips_qs = self._build_payslip_queryset(filters)
            
            if not payslips_qs.exists():
                return {
                    'report_type': 'MUSTER_ROLL',
                    'data': [],
                    'columns': [],
                    'message': 'No data found for the specified filters'
                }
            
            # Extract base payslip data
            data = []
            dynamic_columns_set = set()
            
            for payslip in payslips_qs.select_related('employee', 'employee__user', 'employee__hr_details', 'employee__salary_details'):
                employee = payslip.employee
                
                row_data = {
                    'employee_number': employee.user.username,
                    'employee_name': employee.user.get_full_name(),
                    'pin_number': employee.pin_no,
                    'month': payslip.payment_period.strftime('%B %Y') if payslip.payment_period else '',
                    'department': employee.hr_details.department.name if hasattr(employee, 'hr_details') and employee.hr_details and employee.hr_details.department else 'N/A',
                    'basic_salary': float(payslip.gross_pay or 0),
                    'gross_pay': float(payslip.gross_pay or 0),
                    'taxable_pay': float(payslip.taxable_pay or 0),
                }
                
                # Add statutory deductions
                row_data['nssf'] = float(payslip.nssf_employee_tier_1 or 0) + float(payslip.nssf_employee_tier_2 or 0)
                row_data['nhif_shif'] = float(payslip.shif_or_nhif_contribution or 0)
                row_data['housing_levy'] = float(payslip.housing_levy or 0)
                row_data['paye'] = float(payslip.paye or 0) - float(payslip.reliefs or 0)
                
                # Add deduction phases
                row_data['deductions_before_tax'] = float(payslip.deductions_before_tax or 0)
                row_data['deductions_after_tax'] = float(payslip.deductions_after_tax or 0)
                row_data['deductions_after_paye'] = float(payslip.deductions_after_paye or 0)
                
                # Add net pay
                row_data['net_pay'] = float(payslip.net_pay or 0)
                
                # Track all columns
                for key in row_data.keys():
                    dynamic_columns_set.add(key)
                
                data.append(row_data)
            
            # Create Polars DataFrame
            df = pl.DataFrame(data)
            
            # Build dynamic column definitions
            base_columns = [
                {'field': 'employee_number', 'header': 'Employee No.'},
                {'field': 'employee_name', 'header': 'Employee Name'},
                {'field': 'pin_number', 'header': 'PIN Number'},
                {'field': 'month', 'header': 'Month'},
                {'field': 'department', 'header': 'Department'},
                {'field': 'basic_salary', 'header': 'Basic Salary'},
            ]
            
            # Add columns that exist in data
            optional_columns = [
                {'field': 'gross_pay', 'header': 'Gross Pay'},
                {'field': 'taxable_pay', 'header': 'Taxable Pay'},
                {'field': 'nssf', 'header': 'NSSF'},
                {'field': 'nhif_shif', 'header': 'NHIF/SHIF'},
                {'field': 'housing_levy', 'header': 'Housing Levy'},
                {'field': 'paye', 'header': 'PAYE'},
                {'field': 'deductions_before_tax', 'header': 'Deductions (Before Tax)'},
                {'field': 'deductions_after_tax', 'header': 'Deductions (After Tax)'},
                {'field': 'deductions_after_paye', 'header': 'Deductions (After PAYE)'},
                {'field': 'net_pay', 'header': 'Net Pay'},
            ]
            
            columns = base_columns + [col for col in optional_columns if col['field'] in dynamic_columns_set]
            
            # Calculate totals for all numeric columns
            totals = {
                'total_employees': len(df),
            }
            
            numeric_fields = [col['field'] for col in columns if col['field'] not in ['employee_number', 'employee_name', 'pin_number', 'month', 'department']]
            for field in numeric_fields:
                if field in df.columns:
                    totals[f'total_{field}'] = float(df[field].sum())
            
            return {
                'report_type': 'MUSTER_ROLL',
                'title': 'Muster Roll Report',
                'data': df.to_dicts(),
                'columns': columns,
                'totals': totals,
                'filters_applied': filters,
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Error generating Muster Roll report: {str(e)}")
            return {
                'report_type': 'MUSTER_ROLL',
                'error': str(e),
                'data': [],
                'columns': [],
            }
    
    def generate_withholding_tax_report(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate Withholding Tax report (for contractors/consultants).
        Shows tax withheld from payments to non-employees.
        """
        try:
            # For withholding tax, we typically look at expense claims or contractor payments
            # This is a simplified version - expand based on your business logic
            from hrm.payroll.models import ExpenseClaims
            
            # Get date range from filters
            payment_period = filters.get('payment_period')
            year = filters.get('year')
            month = filters.get('month')
            
            claims_qs = ExpenseClaims.objects.filter(
                is_paid=True,
                delete_status=False
            )
            
            if payment_period:
                if isinstance(payment_period, str):
                    payment_period = datetime.strptime(payment_period, '%Y-%m-%d').date()
                claims_qs = claims_qs.filter(
                    payment_date__year=payment_period.year,
                    payment_date__month=payment_period.month
                )
            elif year:
                claims_qs = claims_qs.filter(payment_date__year=year)
                if month:
                    claims_qs = claims_qs.filter(payment_date__month=month)
            
            # Apply other filters
            if filters.get('employee_ids'):
                claims_qs = claims_qs.filter(employee_id__in=filters['employee_ids'])
            
            if not claims_qs.exists():
                return {
                    'report_type': 'WITHHOLDING_TAX',
                    'data': [],
                    'columns': [],
                    'message': 'No withholding tax data found for the specified filters'
                }
            
            # Extract data
            data = []
            for claim in claims_qs.select_related('employee', 'employee__user'):
                employee = claim.employee
                
                # Withholding tax is typically 5% for services
                withholding_rate = 0.05
                withholding_amount = float(claim.amount or 0) * withholding_rate
                net_amount = float(claim.amount or 0) - withholding_amount
                
                data.append({
                    'employee_number': employee.user.username,
                    'employee_name': employee.user.get_full_name(),
                    'pin_number': employee.pin_no,
                    'payment_date': claim.payment_date.strftime('%Y-%m-%d') if claim.payment_date else '',
                    'category': claim.category,
                    'gross_amount': float(claim.amount or 0),
                    'withholding_rate': withholding_rate * 100,
                    'withholding_amount': withholding_amount,
                    'net_amount': net_amount,
                })
            
            # Create Polars DataFrame
            df = pl.DataFrame(data)
            
            columns = [
                {'field': 'employee_number', 'header': 'Employee No.'},
                {'field': 'employee_name', 'header': 'Employee Name'},
                {'field': 'pin_number', 'header': 'PIN Number'},
                {'field': 'payment_date', 'header': 'Payment Date'},
                {'field': 'category', 'header': 'Category'},
                {'field': 'gross_amount', 'header': 'Gross Amount'},
                {'field': 'withholding_rate', 'header': 'WHT Rate (%)'},
                {'field': 'withholding_amount', 'header': 'Withholding Tax'},
                {'field': 'net_amount', 'header': 'Net Amount'},
            ]
            
            totals = {
                'total_transactions': len(df),
                'total_gross_amount': float(df['gross_amount'].sum()),
                'total_withholding_tax': float(df['withholding_amount'].sum()),
                'total_net_amount': float(df['net_amount'].sum()),
            }
            
            return {
                'report_type': 'WITHHOLDING_TAX',
                'title': 'Withholding Tax Report',
                'data': df.to_dicts(),
                'columns': columns,
                'totals': totals,
                'filters_applied': filters,
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Error generating Withholding Tax report: {str(e)}")
            return {
                'report_type': 'WITHHOLDING_TAX',
                'error': str(e),
                'data': [],
                'columns': [],
            }
    
    def generate_variance_report(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate Payroll Variance report comparing periods.
        Shows changes in payroll amounts between periods.
        """
        try:
            current_period = filters.get('current_period')
            previous_period = filters.get('previous_period')
            
            if not current_period or not previous_period:
                return {
                    'report_type': 'VARIANCE',
                    'error': 'Both current_period and previous_period are required',
                    'data': [],
                    'columns': [],
                }
            
            # Parse periods
            if isinstance(current_period, str):
                current_period = datetime.strptime(current_period, '%Y-%m-%d').date()
            if isinstance(previous_period, str):
                previous_period = datetime.strptime(previous_period, '%Y-%m-%d').date()
            
            # Get payslips for both periods
            current_payslips = Payslip.objects.filter(
                payment_period=current_period,
                delete_status=False
            )
            
            previous_payslips = Payslip.objects.filter(
                payment_period=previous_period,
                delete_status=False
            )
            
            # Apply other filters
            current_payslips = self._apply_filters(current_payslips, filters)
            previous_payslips = self._apply_filters(previous_payslips, filters)
            
            # Build variance data
            data = []
            
            # Get all employees in current period
            for current_slip in current_payslips.select_related('employee', 'employee__user'):
                employee = current_slip.employee
                
                # Find matching previous payslip
                previous_slip = previous_payslips.filter(employee=employee).first()
                
                current_net_pay = float(current_slip.net_pay or 0)
                previous_net_pay = float(previous_slip.net_pay or 0) if previous_slip else 0.0
                variance = current_net_pay - previous_net_pay
                variance_percent = (variance / previous_net_pay * 100) if previous_net_pay > 0 else 0
                
                data.append({
                    'employee_number': employee.user.username,
                    'employee_name': employee.user.get_full_name(),
                    'department': employee.hr_details.department.name if hasattr(employee, 'hr_details') and employee.hr_details and employee.hr_details.department else 'N/A',
                    'previous_net_pay': previous_net_pay,
                    'current_net_pay': current_net_pay,
                    'variance': variance,
                    'variance_percent': variance_percent,
                })
            
            # Create Polars DataFrame
            df = pl.DataFrame(data)
            
            # Sort by absolute variance (highest changes first)
            df = df.with_columns(
                pl.col('variance').abs().alias('abs_variance')
            ).sort('abs_variance', descending=True).drop('abs_variance')
            
            columns = [
                {'field': 'employee_number', 'header': 'Employee No.'},
                {'field': 'employee_name', 'header': 'Employee Name'},
                {'field': 'department', 'header': 'Department'},
                {'field': 'previous_net_pay', 'header': 'Previous Net Pay'},
                {'field': 'current_net_pay', 'header': 'Current Net Pay'},
                {'field': 'variance', 'header': 'Variance'},
                {'field': 'variance_percent', 'header': 'Variance (%)'},
            ]
            
            totals = {
                'total_employees': len(df),
                'total_previous_net_pay': float(df['previous_net_pay'].sum()),
                'total_current_net_pay': float(df['current_net_pay'].sum()),
                'total_variance': float(df['variance'].sum()),
            }
            
            return {
                'report_type': 'VARIANCE',
                'title': 'Payroll Variance Report',
                'data': df.to_dicts(),
                'columns': columns,
                'totals': totals,
                'current_period': current_period.strftime('%B %Y'),
                'previous_period': previous_period.strftime('%B %Y'),
                'filters_applied': filters,
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Error generating Variance report: {str(e)}")
            return {
                'report_type': 'VARIANCE',
                'error': str(e),
                'data': [],
                'columns': [],
            }
    
    def _build_payslip_queryset(self, filters: Dict[str, Any]):
        """Build base payslip queryset with common filters."""
        queryset = Payslip.objects.filter(delete_status=False)
        
        # Payment period filter
        payment_period = filters.get('payment_period')
        if payment_period:
            if isinstance(payment_period, str):
                payment_period = datetime.strptime(payment_period, '%Y-%m-%d').date()
            queryset = queryset.filter(
                payment_period__year=payment_period.year,
                payment_period__month=payment_period.month
            )
        
        # Year filter
        year = filters.get('year')
        if year:
            queryset = queryset.filter(payment_period__year=year)
        
        # Month filter (if year also provided)
        month = filters.get('month')
        if month and year:
            queryset = queryset.filter(payment_period__month=month)
        
        return self._apply_filters(queryset, filters)
    
    def _apply_filters(self, queryset, filters: Dict[str, Any]):
        """Apply additional filters to queryset."""
        # Employee IDs filter
        if filters.get('employee_ids'):
            queryset = queryset.filter(employee_id__in=filters['employee_ids'])
        
        # Department IDs filter
        if filters.get('department_ids'):
            queryset = queryset.filter(employee__hr_details__department_id__in=filters['department_ids'])
        
        # Region IDs filter
        if filters.get('region_ids'):
            queryset = queryset.filter(employee__hr_details__region_id__in=filters['region_ids'])
        
        # Branch ID filter
        if filters.get('branch_id'):
            queryset = queryset.filter(employee__hr_details__branch_id=filters['branch_id'])
        
        # Status filter
        if filters.get('payroll_status'):
            queryset = queryset.filter(payroll_status=filters['payroll_status'])
        
        return queryset

    def get_active_deductions_and_earnings(self, payslips_qs) -> Dict[str, List[str]]:
        """
        Detect which deductions and earnings are active (non-zero) in the payslip data.
        This allows for flexible column generation based on actual payroll configuration.
        
        Returns:
            Dict with 'deductions' and 'earnings' lists containing active field names
        """
        if not payslips_qs.exists():
            return {'deductions': [], 'earnings': []}
        
        # Fields to check for deductions
        deduction_fields = [
            'nssf_employee_tier_1', 'nssf_employee_tier_2', 'nhif_contribution',
            'shif_or_nhif_contribution', 'housing_levy', 'nita_contribution',
            'income_tax', 'other_deductions', 'advance_pay_deduction', 'loan_deduction'
        ]
        
        # Fields to check for earnings
        earnings_fields = [
            'basic_pay', 'allowances', 'overtime_hours', 'overtime_amount',
            'bonus', 'commission', 'car_allowance', 'housing_allowance',
            'transport_allowance', 'responsibility_allowance', 'fringe_benefit_tax'
        ]
        
        active_deductions = []
        active_earnings = []
        
        # Check which deductions have non-zero values
        for field in deduction_fields:
            try:
                if payslips_qs.filter(**{f'{field}__gt': 0}).exists():
                    active_deductions.append(field)
            except Exception:
                pass  # Field may not exist in model
        
        # Check which earnings have non-zero values
        for field in earnings_fields:
            try:
                if payslips_qs.filter(**{f'{field}__gt': 0}).exists():
                    active_earnings.append(field)
            except Exception:
                pass  # Field may not exist in model
        
        return {
            'deductions': active_deductions,
            'earnings': active_earnings
        }
    
    def get_dynamic_columns_for_muster_roll(self, payslips_qs) -> Dict[str, Any]:
        """
        Generate dynamic column definitions for muster roll based on active fields.
        This ensures muster roll only shows relevant columns for the current payroll.
        
        Returns:
            Dict with column definitions and metadata
        """
        active = self.get_active_deductions_and_earnings(payslips_qs)
        
        # Base columns (always present)
        columns = [
            {'field': 'staff_number', 'header': 'Staff No.'},
            {'field': 'employee_name', 'header': 'Employee Name'},
            {'field': 'basic_pay', 'header': 'Basic Pay'},
        ]
        
        # Add active earnings as columns
        earnings_headers = {
            'allowances': 'Allowances',
            'overtime_hours': 'Overtime Hours',
            'overtime_amount': 'Overtime Amount',
            'bonus': 'Bonus',
            'commission': 'Commission',
            'car_allowance': 'Car Allowance',
            'housing_allowance': 'Housing Allowance',
            'transport_allowance': 'Transport Allowance',
            'responsibility_allowance': 'Responsibility Allowance',
        }
        
        for field in active['earnings']:
            if field in earnings_headers:
                columns.append({'field': field, 'header': earnings_headers[field]})
        
        # Gross pay (calculated field)
        columns.append({'field': 'gross_pay', 'header': 'Gross Pay'})
        
        # Add active deductions as columns
        deductions_headers = {
            'nssf_employee_tier_1': 'NSSF Tier 1',
            'nssf_employee_tier_2': 'NSSF Tier 2',
            'nhif_contribution': 'NHIF',
            'shif_or_nhif_contribution': 'SHIF/NHIF',
            'housing_levy': 'Housing Levy',
            'nita_contribution': 'NITA',
            'income_tax': 'Income Tax',
            'advance_pay_deduction': 'Advance Pay',
            'loan_deduction': 'Loan Deduction',
            'other_deductions': 'Other Deductions',
        }
        
        for field in active['deductions']:
            if field in deductions_headers:
                columns.append({'field': field, 'header': deductions_headers[field]})
        
        # Net pay (calculated field)
        columns.append({'field': 'net_pay', 'header': 'Net Pay'})
        
        return {
            'columns': columns,
            'active_earnings': active['earnings'],
            'active_deductions': active['deductions'],
            'column_count': len(columns)
        }
    
    def get_flexible_muster_roll_data(self, payslips_qs) -> Dict[str, Any]:
        """
        Generate muster roll data with flexible columns that adapt to payroll configuration.
        Columns change based on which deductions/earnings are active in the current month.
        
        Returns:
            Dict with data, columns, and totals
        """
        try:
            if not payslips_qs.exists():
                return {
                    'data': [],
                    'columns': [],
                    'totals': {},
                    'message': 'No payslip data available'
                }
            
            # Get dynamic columns
            dynamic_config = self.get_dynamic_columns_for_muster_roll(payslips_qs)
            columns = dynamic_config['columns']
            
            # Build data rows
            data = []
            for payslip in payslips_qs.select_related('employee', 'employee__user'):
                employee = payslip.employee
                row = {
                    'staff_number': employee.user.username,
                    'employee_name': employee.user.get_full_name(),
                    'basic_pay': float(payslip.basic_pay or 0),
                    'gross_pay': float(payslip.gross_pay or 0),
                    'net_pay': float(payslip.net_pay or 0),
                }
                
                # Add active earnings
                for field in dynamic_config['active_earnings']:
                    row[field] = float(getattr(payslip, field) or 0)
                
                # Add active deductions
                for field in dynamic_config['active_deductions']:
                    row[field] = float(getattr(payslip, field) or 0)
                
                data.append(row)
            
            # Calculate totals for numeric columns
            df = pl.DataFrame(data)
            totals = {}
            for col_def in columns:
                field = col_def['field']
                if field in df.columns and df[field].dtype in [pl.Float32, pl.Float64, pl.Int32, pl.Int64]:
                    totals[field] = float(df[field].sum())
            
            return {
                'data': data,
                'columns': columns,
                'totals': totals,
                'dynamic_config': dynamic_config
            }
        
        except Exception as e:
            logger.error(f"Error generating flexible muster roll data: {str(e)}", exc_info=True)
            return {
                'data': [],
                'columns': [],
                'totals': {},
                'error': str(e)
            }

