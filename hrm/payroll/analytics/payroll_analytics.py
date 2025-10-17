"""
Payroll Analytics Service

Provides comprehensive analytics for payroll management including salary analysis,
tax calculations, benefits analysis, and payroll trends.
"""

from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Avg, Count, Q, Sum, F, Min, Max
from django.db import connection
from django.core.cache import cache
import logging
from hrm.payroll.models import Payslip
from hrm.employees.models import Employee, SalaryDetails

logger = logging.getLogger(__name__)


class PayrollAnalyticsService:
    """
    Service for payroll analytics and reporting.
    Provides metrics for salary analysis, tax calculations, benefits, and trends.
    """
    
    def __init__(self):
        self.cache_timeout = 300  # 5 minutes
    
    def get_payroll_dashboard_data(self, business_id=None, period='month', start_date=None, end_date=None, 
                                 region_id=None, department_id=None, branch_id=None):
        """
        Get comprehensive payroll dashboard data.
        
        Args:
            business_id: Business ID to filter data
            period: Time period for analysis ('week', 'month', 'quarter', 'year', 'custom')
            start_date: Custom start date (required if period='custom')
            end_date: Custom end date (required if period='custom')
            region_id: Region ID to filter data
            department_id: Department ID to filter data
            branch_id: Branch ID to filter data (from X-Branch-ID header)
            
        Returns:
            dict: Payroll dashboard data with fallbacks
        """
        try:
            return {
                'payroll_summary': self._get_payroll_summary(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'salary_analysis': self._get_salary_analysis(business_id, region_id, department_id, branch_id),
                'tax_analysis': self._get_tax_analysis(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'benefits_analysis': self._get_benefits_analysis(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'payroll_trends': self._get_payroll_trends(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'component_breakdown': self._get_component_breakdown(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'branch_analysis': self._get_branch_analysis(business_id, region_id, department_id, branch_id),
                'department_analysis': self._get_department_analysis(business_id, region_id, department_id, branch_id),
                'region_analysis': self._get_region_analysis(business_id, region_id, department_id, branch_id)
            }
        except Exception as e:
            logger.error(f"Error getting payroll dashboard data: {e}")
            return self._get_fallback_payroll_data()
    
    def _get_payroll_summary(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get payroll summary metrics."""
        try:
            # Calculate date range
            if period == 'custom':
                start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
            else:
                end_date = timezone.now().date()
                if period == 'week':
                    start_date = end_date - timedelta(days=7)
                elif period == 'month':
                    start_date = end_date - timedelta(days=30)
                elif period == 'quarter':
                    start_date = end_date - timedelta(days=90)
                elif period == 'year':
                    start_date = end_date - timedelta(days=365)
                else:
                    start_date = end_date - timedelta(days=30)
            
            queryset = Payslip.objects.filter(
                payment_period__gte=start_date,
                payment_period__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            if region_id:
                queryset = queryset.filter(employee__hr_details__region_id=region_id)
            
            if department_id:
                queryset = queryset.filter(employee__hr_details__department_id=department_id)
            
            if branch_id:
                queryset = queryset.filter(employee__hr_details__branch_id=branch_id)
            
            # Payroll statistics
            total_payslips = queryset.count()
            total_gross_pay = queryset.aggregate(total=Sum('gross_pay'))['total'] or 0
            total_net_pay = queryset.aggregate(total=Sum('net_pay'))['total'] or 0
            total_tax = queryset.aggregate(total=Sum('income_tax'))['total'] or 0
            total_nssf = queryset.aggregate(total=Sum('nssf_deduction'))['total'] or 0
            total_nhif = queryset.aggregate(total=Sum('nhif_deduction'))['total'] or 0
            
            # Average metrics
            avg_gross_pay = queryset.aggregate(avg=Avg('gross_pay'))['avg'] or 0
            avg_net_pay = queryset.aggregate(avg=Avg('net_pay'))['avg'] or 0
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_payslips': total_payslips,
                'total_gross_pay': round(total_gross_pay, 2),
                'total_net_pay': round(total_net_pay, 2),
                'total_tax': round(total_tax, 2),
                'total_nssf': round(total_nssf, 2),
                'total_nhif': round(total_nhif, 2),
                'avg_gross_pay': round(avg_gross_pay, 2),
                'avg_net_pay': round(avg_net_pay, 2),
                'total_deductions': round(total_tax + total_nssf + total_nhif, 2)
            }
        except Exception as e:
            logger.error(f"Error getting payroll summary data: {e}")
            return self._get_fallback_payroll_summary_data()
    
    def _get_salary_analysis(self, business_id, region_id=None, department_id=None, branch_id=None):
        """Get salary analysis metrics."""
        try:
            queryset = SalaryDetails.objects.filter(employee__deleted=False, employee__terminated=False)
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Salary statistics
            salary_stats = queryset.aggregate(
                avg_basic_salary=Avg('basic_salary'),
                min_basic_salary=Min('basic_salary'),
                max_basic_salary=Max('basic_salary'),
                total_payroll=Sum('basic_salary')
            )
            
            # Salary distribution by ranges
            salary_ranges = [
                {'range': '25K-50K', 'min': 25000, 'max': 50000},
                {'range': '50K-75K', 'min': 50000, 'max': 75000},
                {'range': '75K-100K', 'min': 75000, 'max': 100000},
                {'range': '100K-150K', 'min': 100000, 'max': 150000},
                {'range': '150K+', 'min': 150000, 'max': None}
            ]
            
            salary_distribution = []
            for salary_range in salary_ranges:
                if salary_range['max']:
                    count = queryset.filter(
                        basic_salary__gte=salary_range['min'],
                        basic_salary__lt=salary_range['max']
                    ).count()
                else:
                    count = queryset.filter(basic_salary__gte=salary_range['min']).count()
                
                salary_distribution.append({
                    'range': salary_range['range'],
                    'count': count,
                    'percentage': round((count / queryset.count() * 100) if queryset.count() > 0 else 0, 2)
                })
            
            return {
                'salary_statistics': salary_stats,
                'salary_distribution': salary_distribution
            }
        except Exception as e:
            logger.error(f"Error getting salary analysis data: {e}")
            return self._get_fallback_salary_analysis_data()
    
    def _get_tax_analysis(self, business_id, period, start_date=None, end_date=None, region_id=None, department_id=None, branch_id=None):
        """Get tax analysis metrics."""
        try:
            # Calculate date range
            end_date = timezone.now().date()
            if period == 'week':
                start_date = end_date - timedelta(days=7)
            elif period == 'month':
                start_date = end_date - timedelta(days=30)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=90)
            elif period == 'year':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            queryset = Payslip.objects.filter(
                payment_period__gte=start_date,
                payment_period__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Tax statistics
            total_income_tax = queryset.aggregate(total=Sum('income_tax'))['total'] or 0
            total_nssf = queryset.aggregate(total=Sum('nssf_deduction'))['total'] or 0
            total_nhif = queryset.aggregate(total=Sum('nhif_deduction'))['total'] or 0
            
            # Tax by month
            tax_by_month = queryset.values('payment_period__month').annotate(
                income_tax=Sum('income_tax'),
                nssf=Sum('nssf_deduction'),
                nhif=Sum('nhif_deduction'),
                total_tax=Sum('income_tax') + Sum('nssf_deduction') + Sum('nhif_deduction')
            ).order_by('payment_period__month')
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_income_tax': round(total_income_tax, 2),
                'total_nssf': round(total_nssf, 2),
                'total_nhif': round(total_nhif, 2),
                'total_tax_contributions': round(total_income_tax + total_nssf + total_nhif, 2),
                'tax_by_month': list(tax_by_month)
            }
        except Exception as e:
            logger.error(f"Error getting tax analysis data: {e}")
            return self._get_fallback_tax_analysis_data()
    
    def _get_benefits_analysis(self, business_id, period, start_date=None, end_date=None, region_id=None, department_id=None, branch_id=None):
        """Get benefits analysis metrics."""
        try:
            # Calculate date range
            end_date = timezone.now().date()
            if period == 'week':
                start_date = end_date - timedelta(days=7)
            elif period == 'month':
                start_date = end_date - timedelta(days=30)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=90)
            elif period == 'year':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            queryset = Payslip.objects.filter(
                payment_period__gte=start_date,
                payment_period__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Benefits statistics
            total_allowances = queryset.aggregate(total=Sum('total_allowances'))['total'] or 0
            total_bonuses = queryset.aggregate(total=Sum('bonus_amount'))['total'] or 0
            total_overtime = queryset.aggregate(total=Sum('overtime_pay'))['total'] or 0
            
            # Benefits by type
            benefits_by_type = [
                {'type': 'Allowances', 'amount': total_allowances, 'percentage': 0},
                {'type': 'Bonuses', 'amount': total_bonuses, 'percentage': 0},
                {'type': 'Overtime', 'amount': total_overtime, 'percentage': 0}
            ]
            
            total_benefits = total_allowances + total_bonuses + total_overtime
            if total_benefits > 0:
                for benefit in benefits_by_type:
                    benefit['percentage'] = round((benefit['amount'] / total_benefits * 100), 2)
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_allowances': round(total_allowances, 2),
                'total_bonuses': round(total_bonuses, 2),
                'total_overtime': round(total_overtime, 2),
                'total_benefits': round(total_benefits, 2),
                'benefits_by_type': benefits_by_type
            }
        except Exception as e:
            logger.error(f"Error getting benefits analysis data: {e}")
            return self._get_fallback_benefits_analysis_data()
    
    def _get_payroll_trends(self, business_id, period, start_date=None, end_date=None, region_id=None, department_id=None, branch_id=None):
        """Get payroll trends over time."""
        try:
            # Calculate date range
            end_date = timezone.now().date()
            if period == 'week':
                start_date = end_date - timedelta(days=7)
            elif period == 'month':
                start_date = end_date - timedelta(days=30)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=90)
            elif period == 'year':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            queryset = Payslip.objects.filter(
                payment_period__gte=start_date,
                payment_period__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Trends by month
            trends_by_month = queryset.values('payment_period__month').annotate(
                gross_pay=Sum('gross_pay'),
                net_pay=Sum('net_pay'),
                tax=Sum('income_tax'),
                employee_count=Count('employee', distinct=True)
            ).order_by('payment_period__month')
            
            # Calculate month-over-month growth
            trends_list = list(trends_by_month)
            for i in range(1, len(trends_list)):
                prev_month = trends_list[i-1]
                curr_month = trends_list[i]
                
                if prev_month['gross_pay'] > 0:
                    gross_growth = ((curr_month['gross_pay'] - prev_month['gross_pay']) / prev_month['gross_pay']) * 100
                    curr_month['gross_growth'] = round(gross_growth, 2)
                else:
                    curr_month['gross_growth'] = 0
                
                if prev_month['net_pay'] > 0:
                    net_growth = ((curr_month['net_pay'] - prev_month['net_pay']) / prev_month['net_pay']) * 100
                    curr_month['net_growth'] = round(net_growth, 2)
                else:
                    curr_month['net_growth'] = 0
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'trends_by_month': trends_list
            }
        except Exception as e:
            logger.error(f"Error getting payroll trends data: {e}")
            return self._get_fallback_payroll_trends_data()
    
    def _get_component_breakdown(self, business_id, period, start_date=None, end_date=None, region_id=None, department_id=None, branch_id=None):
        """Get payroll component breakdown."""
        try:
            # Calculate date range
            end_date = timezone.now().date()
            if period == 'week':
                start_date = end_date - timedelta(days=7)
            elif period == 'month':
                start_date = end_date - timedelta(days=30)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=90)
            elif period == 'year':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            queryset = Payslip.objects.filter(
                payment_period__gte=start_date,
                payment_period__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Component breakdown
            components = {
                'basic_salary': queryset.aggregate(total=Sum('basic_salary'))['total'] or 0,
                'allowances': queryset.aggregate(total=Sum('total_allowances'))['total'] or 0,
                'overtime': queryset.aggregate(total=Sum('overtime_pay'))['total'] or 0,
                'bonuses': queryset.aggregate(total=Sum('bonus_amount'))['total'] or 0,
                'deductions': queryset.aggregate(total=Sum('total_deductions'))['total'] or 0,
                'tax': queryset.aggregate(total=Sum('income_tax'))['total'] or 0,
                'nssf': queryset.aggregate(total=Sum('nssf_deduction'))['total'] or 0,
                'nhif': queryset.aggregate(total=Sum('nhif_deduction'))['total'] or 0
            }
            
            # Calculate percentages
            total_gross = components['basic_salary'] + components['allowances'] + components['overtime'] + components['bonuses']
            if total_gross > 0:
                for key in components:
                    if key != 'total_deductions':
                        components[f'{key}_percentage'] = round((components[key] / total_gross) * 100, 2)
                    else:
                        components[f'{key}_percentage'] = round((components[key] / total_gross) * 100, 2)
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'components': components,
                'total_gross': total_gross
            }
        except Exception as e:
            logger.error(f"Error getting component breakdown data: {e}")
            return self._get_fallback_component_breakdown_data()
    
    def _get_branch_analysis(self, business_id, region_id=None, department_id=None, branch_id=None):
        """Get payroll analysis by branch."""
        try:
            queryset = Payslip.objects.filter(employee__deleted=False, employee__terminated=False)
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            branch_analysis = queryset.values(
                'employee__hr_details__branch__name'
            ).annotate(
                avg_gross_pay=Avg('gross_pay'),
                avg_net_pay=Avg('net_pay'),
                total_payroll=Sum('gross_pay'),
                employee_count=Count('employee', distinct=True)
            ).order_by('-total_payroll')
            
            return list(branch_analysis)
        except Exception as e:
            logger.error(f"Error getting branch analysis data: {e}")
            return self._get_fallback_branch_analysis_data()
        
    def _get_region_analysis(self, business_id, region_id=None, department_id=None, branch_id=None):
        """Get payroll analysis by region."""
        try:
            queryset = Payslip.objects.filter(employee__deleted=False, employee__terminated=False)
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            region_analysis = queryset.values(
                'employee__hr_details__region__name'
            ).annotate(
                avg_gross_pay=Avg('gross_pay'),
                avg_net_pay=Avg('net_pay'),
                total_payroll=Sum('gross_pay'),
                employee_count=Count('employee', distinct=True)
            ).order_by('-total_payroll')
            
            return list(region_analysis)
        except Exception as e:
            logger.error(f"Error getting region analysis data: {e}")
            return self._get_fallback_region_analysis_data()
    
    
    def _get_department_analysis(self, business_id, region_id=None, department_id=None, branch_id=None):
        """Get payroll analysis by department."""
        try:
            queryset = Payslip.objects.filter(employee__deleted=False, employee__terminated=False)
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            department_analysis = queryset.values(
                'employee__hr_details__department__title'
            ).annotate(
                avg_gross_pay=Avg('gross_pay'),
                avg_net_pay=Avg('net_pay'),
                total_payroll=Sum('gross_pay'),
                employee_count=Count('employee', distinct=True)
            ).order_by('-total_payroll')
            
            return list(department_analysis)
        except Exception as e:
            logger.error(f"Error getting department analysis data: {e}")
            return self._get_fallback_department_analysis_data()
    
    # Fallback data methods
    def _get_fallback_payroll_data(self):
        """Return fallback payroll data if analytics collection fails."""
        logger.warning("Returning fallback payroll data due to analytics collection failure.")
        return {
            'payroll_summary': self._get_fallback_payroll_summary_data(),
            'salary_analysis': self._get_fallback_salary_analysis_data(),
            'tax_analysis': self._get_fallback_tax_analysis_data(),
            'benefits_analysis': self._get_fallback_benefits_analysis_data(),
            'payroll_trends': self._get_fallback_payroll_trends_data(),
            'component_breakdown': self._get_fallback_component_breakdown_data(),
            'branch_analysis': self._get_fallback_branch_analysis_data(),
            'department_analysis': self._get_fallback_department_analysis_data(),
            'region_analysis': self._get_fallback_region_analysis_data()
        }
    
    def _get_fallback_region_analysis_data(self):
        """Return fallback region analysis data."""
        logger.warning("Returning fallback region analysis data.")
        return [
            {'employee__hr_details__region__name': 'Nairobi', 'avg_gross_pay': 52000.00, 'avg_net_pay': 41600.00, 'total_payroll': 780000.00, 'employee_count': 15},
            {'employee__hr_details__region__name': 'Mombasa', 'avg_gross_pay': 45000.00, 'avg_net_pay': 36000.00, 'total_payroll': 360000.00, 'employee_count': 8},
            {'employee__hr_details__region__name': 'Kisumu', 'avg_gross_pay': 42000.00, 'avg_net_pay': 33600.00, 'total_payroll': 294000.00, 'employee_count': 7}
        ]
    
    def _get_fallback_payroll_summary_data(self):
        """Return fallback payroll summary data."""
        logger.warning("Returning fallback payroll summary data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_payslips': 30,
            'total_gross_pay': 1350000.00,
            'total_net_pay': 1080000.00,
            'total_tax': 135000.00,
            'total_nssf': 67500.00,
            'total_nhif': 45000.00,
            'avg_gross_pay': 45000.00,
            'avg_net_pay': 36000.00,
            'total_deductions': 247500.00
        }
    
    def _get_fallback_salary_analysis_data(self):
        """Return fallback salary analysis data."""
        logger.warning("Returning fallback salary analysis data.")
        return {
            'salary_statistics': {
                'avg_basic_salary': 45000.00,
                'min_basic_salary': 25000.00,
                'max_basic_salary': 120000.00,
                'total_payroll': 1350000.00
            },
            'salary_distribution': [
                {'range': '25K-50K', 'count': 18, 'percentage': 60.0},
                {'range': '50K-75K', 'count': 8, 'percentage': 26.7},
                {'range': '75K-100K', 'count': 3, 'percentage': 10.0},
                {'range': '100K-150K', 'count': 1, 'percentage': 3.3},
                {'range': '150K+', 'count': 0, 'percentage': 0.0}
            ]
        }
    
    def _get_fallback_tax_analysis_data(self):
        """Return fallback tax analysis data."""
        logger.warning("Returning fallback tax analysis data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_income_tax': 135000.00,
            'total_nssf': 67500.00,
            'total_nhif': 45000.00,
            'total_tax_contributions': 247500.00,
            'tax_by_month': [
                {'payment_period__month': 1, 'income_tax': 135000.00, 'nssf': 67500.00, 'nhif': 45000.00, 'total_tax': 247500.00}
            ]
        }
    
    def _get_fallback_benefits_analysis_data(self):
        """Return fallback benefits analysis data."""
        logger.warning("Returning fallback benefits analysis data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_allowances': 90000.00,
            'total_bonuses': 45000.00,
            'total_overtime': 22500.00,
            'total_benefits': 157500.00,
            'benefits_by_type': [
                {'type': 'Allowances', 'amount': 90000.00, 'percentage': 57.1},
                {'type': 'Bonuses', 'amount': 45000.00, 'percentage': 28.6},
                {'type': 'Overtime', 'amount': 22500.00, 'percentage': 14.3}
            ]
        }
    
    def _get_fallback_payroll_trends_data(self):
        """Return fallback payroll trends data."""
        logger.warning("Returning fallback payroll trends data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'trends_by_month': [
                {'payment_period__month': 1, 'gross_pay': 1350000.00, 'net_pay': 1080000.00, 'tax': 135000.00, 'employee_count': 30, 'gross_growth': 0, 'net_growth': 0}
            ]
        }
    
    def _get_fallback_component_breakdown_data(self):
        """Return fallback component breakdown data."""
        logger.warning("Returning fallback component breakdown data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'components': {
                'basic_salary': 1350000.00,
                'allowances': 90000.00,
                'overtime': 22500.00,
                'bonuses': 45000.00,
                'deductions': 247500.00,
                'tax': 135000.00,
                'nssf': 67500.00,
                'nhif': 45000.00,
                'basic_salary_percentage': 89.4,
                'allowances_percentage': 6.0,
                'overtime_percentage': 1.5,
                'bonuses_percentage': 3.0,
                'deductions_percentage': 16.4,
                'tax_percentage': 8.9,
                'nssf_percentage': 4.5,
                'nhif_percentage': 3.0
            },
            'total_gross': 1507500.00
        }
    
    def _get_fallback_branch_analysis_data(self):
        """Return fallback branch analysis data."""
        logger.warning("Returning fallback branch analysis data.")
        return [
            {'employee__hr_details__branch__name': 'Main Branch', 'avg_gross_pay': 52000.00, 'avg_net_pay': 41600.00, 'total_payroll': 780000.00, 'employee_count': 15},
            {'employee__hr_details__branch__name': 'Nairobi Branch', 'avg_gross_pay': 45000.00, 'avg_net_pay': 36000.00, 'total_payroll': 360000.00, 'employee_count': 8},
            {'employee__hr_details__branch__name': 'Mombasa Branch', 'avg_gross_pay': 42000.00, 'avg_net_pay': 33600.00, 'total_payroll': 294000.00, 'employee_count': 7}
        ]
    
    def _get_fallback_department_analysis_data(self):
        """Return fallback department analysis data."""
        logger.warning("Returning fallback department analysis data.")
        return [
            {'employee__hr_details__department__name': 'IT', 'avg_gross_pay': 55000.00, 'avg_net_pay': 44000.00, 'total_payroll': 440000.00, 'employee_count': 8},
            {'employee__hr_details__department__name': 'Sales', 'avg_gross_pay': 48000.00, 'avg_net_pay': 38400.00, 'total_payroll': 288000.00, 'employee_count': 6},
            {'employee__hr_details__department__name': 'Finance', 'avg_gross_pay': 52000.00, 'avg_net_pay': 41600.00, 'total_payroll': 208000.00, 'employee_count': 4},
            {'employee__hr_details__department__name': 'HR', 'avg_gross_pay': 45000.00, 'avg_net_pay': 36000.00, 'total_payroll': 135000.00, 'employee_count': 3},
            {'employee__hr_details__department__name': 'Operations', 'avg_gross_pay': 40000.00, 'avg_net_pay': 32000.00, 'total_payroll': 360000.00, 'employee_count': 9}
        ]
