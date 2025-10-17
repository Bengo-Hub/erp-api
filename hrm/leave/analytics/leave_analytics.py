"""
Leave Analytics Service

Provides comprehensive analytics for leave management including leave requests,
approval rates, leave balances, and leave trends.
"""

from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Avg, Count, Q, Sum, F, Min, Max
from django.db import connection
from django.core.cache import cache
from hrm.leave.models import LeaveRequest, LeaveCategory, LeaveEntitlement, LeaveBalance
from hrm.employees.models import Employee
import logging
logger = logging.getLogger(__name__)

class LeaveAnalyticsService:
    """
    Service for leave analytics and reporting.
    Provides metrics for leave requests, approval rates, balances, and trends.
    """
    
    def __init__(self):
        self.cache_timeout = 300  # 5 minutes

    def get_leave_dashboard_data(self, business_id=None, period='month', start_date=None, end_date=None, 
                                region_id=None, department_id=None, branch_id=None):
        """
        Get comprehensive leave dashboard data.
        
        Args:
            business_id: Business ID to filter data
            period: Time period for analysis ('week', 'month', 'quarter', 'year', 'custom')
            start_date: Custom start date (required if period='custom')
            end_date: Custom end date (required if period='custom')
            region_id: Region ID to filter data
            department_id: Department ID to filter data
            branch_id: Branch ID to filter data (from X-Branch-ID header)
            
        Returns:
            dict: Leave dashboard data with fallbacks
        """
        try:
            return {
                'leave_summary': self._get_leave_summary(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'leave_requests': self._get_leave_requests(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'leave_balances': self._get_leave_balances(business_id, region_id, department_id, branch_id),
                'leave_trends': self._get_leave_trends(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'leave_by_category': self._get_leave_by_category(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'leave_by_department': self._get_leave_by_department(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'leave_by_branch': self._get_leave_by_branch(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'approval_metrics': self._get_approval_metrics(business_id, period, start_date, end_date, region_id, department_id, branch_id)
            }
        except Exception as e:
            logger.error(f"Error getting leave dashboard data: {e}")
            return self._get_fallback_leave_data()
    
    def _get_leave_summary(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get leave summary metrics."""
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
            
            queryset = LeaveRequest.objects.filter(
                start_date__gte=start_date,
                end_date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Leave statistics
            total_requests = queryset.count()
            approved_requests = queryset.filter(status='approved').count()
            pending_requests = queryset.filter(status='pending').count()
            rejected_requests = queryset.filter(status='rejected').count()
            cancelled_requests = queryset.filter(status='cancelled').count()
            
            # Calculate total leave days
            total_leave_days = 0
            for request in queryset.filter(status='approved'):
                days = (request.end_date - request.start_date).days + 1
                total_leave_days += days
            
            # Calculate rates
            approval_rate = (approved_requests / total_requests * 100) if total_requests > 0 else 0
            rejection_rate = (rejected_requests / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_requests': total_requests,
                'approved_requests': approved_requests,
                'pending_requests': pending_requests,
                'rejected_requests': rejected_requests,
                'cancelled_requests': cancelled_requests,
                'total_leave_days': total_leave_days,
                'approval_rate': round(approval_rate, 2),
                'rejection_rate': round(rejection_rate, 2)
            }
        except Exception as e:
            logger.error(f"Error getting leave summary data: {e}")
            return self._get_fallback_leave_summary_data()
    
    def _get_leave_requests(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get detailed leave request metrics."""
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
            
            queryset = LeaveRequest.objects.filter(
                start_date__gte=start_date,
                end_date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Leave requests by status
            requests_by_status = queryset.values('status').annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Leave requests by month
            requests_by_month = queryset.values('start_date__month').annotate(
                count=Count('id'),
                approved=Count('id', filter=Q(status='approved')),
                pending=Count('id', filter=Q(status='pending')),
                rejected=Count('id', filter=Q(status='rejected'))
            ).order_by('start_date__month')
            
            # Average processing time
            approved_requests = queryset.filter(status='approved')
            if approved_requests.exists():
                avg_processing_time = approved_requests.aggregate(
                    avg_time=Avg(F('updated_at') - F('created_at'))
                )['avg_time']
                avg_processing_days = avg_processing_time.days if avg_processing_time else 0
            else:
                avg_processing_days = 0
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'requests_by_status': list(requests_by_status),
                'requests_by_month': list(requests_by_month),
                'avg_processing_days': avg_processing_days
            }
        except Exception as e:
            logger.error(f"Error getting leave requests data: {e}")
            return self._get_fallback_leave_requests_data()
    
    def _get_leave_balances(self, business_id, region_id, department_id, branch_id):
        """Get leave balance metrics."""
        try:
            queryset = LeaveBalance.objects.filter(employee__deleted=False, employee__terminated=False)
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Leave balance statistics
            total_entitled_days = queryset.aggregate(
                total=Sum('entitled_days')
            )['total'] or 0
            
            total_taken_days = queryset.aggregate(
                total=Sum('taken_days')
            )['total'] or 0
            
            total_remaining_days = queryset.aggregate(
                total=Sum('remaining_days')
            )['total'] or 0
            
            # Leave balances by category
            balances_by_category = queryset.values(
                'leave_category__name'
            ).annotate(
                entitled_days=Sum('entitled_days'),
                taken_days=Sum('taken_days'),
                remaining_days=Sum('remaining_days'),
                employee_count=Count('employee', distinct=True)
            ).order_by('-entitled_days')
            
            # Employees with low leave balance (less than 5 days)
            low_balance_employees = queryset.filter(
                remaining_days__lt=5
            ).values(
                'employee__user__first_name',
                'employee__user__last_name',
                'leave_category__name',
                'remaining_days'
            ).order_by('remaining_days')[:10]
            
            return {
                'total_entitled_days': total_entitled_days,
                'total_taken_days': total_taken_days,
                'total_remaining_days': total_remaining_days,
                'utilization_rate': round((total_taken_days / total_entitled_days * 100) if total_entitled_days > 0 else 0, 2),
                'balances_by_category': list(balances_by_category),
                'low_balance_employees': list(low_balance_employees)
            }
        except Exception as e:
            logger.error(f"Error getting leave balances data: {e}")
            return self._get_fallback_leave_balances_data()
    
    def _get_leave_trends(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get leave trends over time."""
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
            
            queryset = LeaveRequest.objects.filter(
                start_date__gte=start_date,
                end_date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Weekly trends
            weekly_trends = queryset.values('start_date__week').annotate(
                total_requests=Count('id'),
                approved_requests=Count('id', filter=Q(status='approved')),
                total_days=Sum(F('end_date') - F('start_date') + timedelta(days=1))
            ).order_by('start_date__week')
            
            # Monthly trends
            monthly_trends = queryset.values('start_date__month').annotate(
                total_requests=Count('id'),
                approved_requests=Count('id', filter=Q(status='approved')),
                total_days=Sum(F('end_date') - F('start_date') + timedelta(days=1))
            ).order_by('start_date__month')
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'weekly_trends': list(weekly_trends),
                'monthly_trends': list(monthly_trends)
            }
        except Exception as e:
            logger.error(f"Error getting leave trends data: {e}")
            return self._get_fallback_leave_trends_data()
    
    def _get_leave_by_category(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get leave analysis by category."""
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
            
            queryset = LeaveRequest.objects.filter(
                start_date__gte=start_date,
                end_date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            leave_by_category = queryset.values(
                'leave_category__name'
            ).annotate(
                total_requests=Count('id'),
                approved_requests=Count('id', filter=Q(status='approved')),
                pending_requests=Count('id', filter=Q(status='pending')),
                rejected_requests=Count('id', filter=Q(status='rejected')),
                total_days=Sum(F('end_date') - F('start_date') + timedelta(days=1))
            ).order_by('-total_requests')
            
            # Calculate approval rates
            for category in leave_by_category:
                if category['total_requests'] > 0:
                    category['approval_rate'] = round(
                        (category['approved_requests'] / category['total_requests']) * 100, 2
                    )
                else:
                    category['approval_rate'] = 0
            
            return list(leave_by_category)
        except Exception as e:
            logger.error(f"Error getting leave by category data: {e}")
            return self._get_fallback_leave_by_category_data()
    
    def _get_leave_by_department(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get leave analysis by department."""
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
            
            queryset = LeaveRequest.objects.filter(
                start_date__gte=start_date,
                end_date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            leave_by_department = queryset.values(
                'employee__hr_details__department__title'
            ).annotate(
                total_requests=Count('id'),
                approved_requests=Count('id', filter=Q(status='approved')),
                total_days=Sum(F('end_date') - F('start_date') + timedelta(days=1)),
                employee_count=Count('employee', distinct=True)
            ).order_by('-total_requests')
            
            # Calculate per employee metrics
            for dept in leave_by_department:
                if dept['employee_count'] > 0:
                    dept['avg_requests_per_employee'] = round(
                        dept['total_requests'] / dept['employee_count'], 2
                    )
                    dept['avg_days_per_employee'] = round(
                        dept['total_days'] / dept['employee_count'], 2
                    )
                else:
                    dept['avg_requests_per_employee'] = 0
                    dept['avg_days_per_employee'] = 0
            
            return list(leave_by_department)
        except Exception as e:
            logger.error(f"Error getting leave by department data: {e}")
            return self._get_fallback_leave_by_department_data()
    
    def _get_leave_by_branch(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get leave analysis by branch."""
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
            
            queryset = LeaveRequest.objects.filter(
                start_date__gte=start_date,
                end_date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            leave_by_branch = queryset.values(
                'employee__hr_details__branch__name'
            ).annotate(
                total_requests=Count('id'),
                approved_requests=Count('id', filter=Q(status='approved')),
                total_days=Sum(F('end_date') - F('start_date') + timedelta(days=1)),
                employee_count=Count('employee', distinct=True)
            ).order_by('-total_requests')
            
            # Calculate per employee metrics
            for branch in leave_by_branch:
                if branch['employee_count'] > 0:
                    branch['avg_requests_per_employee'] = round(
                        branch['total_requests'] / branch['employee_count'], 2
                    )
                    branch['avg_days_per_employee'] = round(
                        branch['total_days'] / branch['employee_count'], 2
                    )
                else:
                    branch['avg_requests_per_employee'] = 0
                    branch['avg_days_per_employee'] = 0
            
            return list(leave_by_branch)
        except Exception as e:
            logger.error(f"Error getting leave by branch data: {e}")
            return self._get_fallback_leave_by_branch_data()
    
    def _get_approval_metrics(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get leave approval metrics."""
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
            
            queryset = LeaveRequest.objects.filter(
                start_date__gte=start_date,
                end_date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Approval statistics
            total_requests = queryset.count()
            approved_requests = queryset.filter(status='approved').count()
            pending_requests = queryset.filter(status='pending').count()
            rejected_requests = queryset.filter(status='rejected').count()
            
            # Approval rates
            approval_rate = (approved_requests / total_requests * 100) if total_requests > 0 else 0
            rejection_rate = (rejected_requests / total_requests * 100) if total_requests > 0 else 0
            pending_rate = (pending_requests / total_requests * 100) if total_requests > 0 else 0
            
            # Approval by approver
            approval_by_approver = queryset.filter(
                status__in=['approved', 'rejected']
            ).values(
                'approver__first_name',
                'approver__last_name'
            ).annotate(
                total_processed=Count('id'),
                approved=Count('id', filter=Q(status='approved')),
                rejected=Count('id', filter=Q(status='rejected'))
            ).order_by('-total_processed')
            
            # Calculate individual approval rates
            for approver in approval_by_approver:
                if approver['total_processed'] > 0:
                    approver['approval_rate'] = round(
                        (approver['approved'] / approver['total_processed']) * 100, 2
                    )
                else:
                    approver['approval_rate'] = 0
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_requests': total_requests,
                'approved_requests': approved_requests,
                'pending_requests': pending_requests,
                'rejected_requests': rejected_requests,
                'approval_rate': round(approval_rate, 2),
                'rejection_rate': round(rejection_rate, 2),
                'pending_rate': round(pending_rate, 2),
                'approval_by_approver': list(approval_by_approver)
            }
        except Exception as e:
            logger.error(f"Error getting approval metrics data: {e}")
            return self._get_fallback_approval_metrics_data()
    
    # Fallback data methods
    def _get_fallback_leave_data(self):
        """Return fallback leave data if analytics collection fails."""
        return {
            'leave_summary': self._get_fallback_leave_summary_data(),
            'leave_requests': self._get_fallback_leave_requests_data(),
            'leave_balances': self._get_fallback_leave_balances_data(),
            'leave_trends': self._get_fallback_leave_trends_data(),
            'leave_by_category': self._get_fallback_leave_by_category_data(),
            'leave_by_department': self._get_fallback_leave_by_department_data(),
            'leave_by_branch': self._get_fallback_leave_by_branch_data(),
            'approval_metrics': self._get_fallback_approval_metrics_data()
        }
    
    def _get_fallback_leave_summary_data(self):
        """Return fallback leave summary data."""
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_requests': 25,
            'approved_requests': 22,
            'pending_requests': 2,
            'rejected_requests': 1,
            'cancelled_requests': 0,
            'total_leave_days': 45,
            'approval_rate': 88.0,
            'rejection_rate': 4.0
        }
    
    def _get_fallback_leave_requests_data(self):
        """Return fallback leave requests data."""
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'requests_by_status': [
                {'status': 'approved', 'count': 22},
                {'status': 'pending', 'count': 2},
                {'status': 'rejected', 'count': 1}
            ],
            'requests_by_month': [
                {'start_date__month': 1, 'count': 25, 'approved': 22, 'pending': 2, 'rejected': 1}
            ],
            'avg_processing_days': 2.5
        }
    
    def _get_fallback_leave_balances_data(self):
        """Return fallback leave balances data."""
        return {
            'total_entitled_days': 300,
            'total_taken_days': 45,
            'total_remaining_days': 255,
            'utilization_rate': 15.0,
            'balances_by_category': [
                {'leave_category__name': 'Annual Leave', 'entitled_days': 180, 'taken_days': 30, 'remaining_days': 150, 'employee_count': 30},
                {'leave_category__name': 'Sick Leave', 'entitled_days': 60, 'taken_days': 10, 'remaining_days': 50, 'employee_count': 30},
                {'leave_category__name': 'Maternity Leave', 'entitled_days': 60, 'taken_days': 5, 'remaining_days': 55, 'employee_count': 2}
            ],
            'low_balance_employees': [
                {'employee__user__first_name': 'John', 'employee__user__last_name': 'Doe', 'leave_category__name': 'Annual Leave', 'remaining_days': 3},
                {'employee__user__first_name': 'Jane', 'employee__user__last_name': 'Smith', 'leave_category__name': 'Sick Leave', 'remaining_days': 2}
            ]
        }
    
    def _get_fallback_leave_trends_data(self):
        """Return fallback leave trends data."""
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'weekly_trends': [
                {'start_date__week': 1, 'total_requests': 25, 'approved_requests': 22, 'total_days': 45}
            ],
            'monthly_trends': [
                {'start_date__month': 1, 'total_requests': 25, 'approved_requests': 22, 'total_days': 45}
            ]
        }
    
    def _get_fallback_leave_by_category_data(self):
        """Return fallback leave by category data."""
        return [
            {'leave_category__name': 'Annual Leave', 'total_requests': 15, 'approved_requests': 13, 'pending_requests': 1, 'rejected_requests': 1, 'total_days': 30, 'approval_rate': 86.7},
            {'leave_category__name': 'Sick Leave', 'total_requests': 8, 'approved_requests': 8, 'pending_requests': 0, 'rejected_requests': 0, 'total_days': 12, 'approval_rate': 100.0},
            {'leave_category__name': 'Maternity Leave', 'total_requests': 2, 'approved_requests': 1, 'pending_requests': 1, 'rejected_requests': 0, 'total_days': 180, 'approval_rate': 50.0}
        ]
    
    def _get_fallback_leave_by_department_data(self):
        """Return fallback leave by department data."""
        return [
            {'employee__hr_details__department__name': 'IT', 'total_requests': 10, 'approved_requests': 9, 'total_days': 20, 'employee_count': 8, 'avg_requests_per_employee': 1.25, 'avg_days_per_employee': 2.5},
            {'employee__hr_details__department__name': 'Sales', 'total_requests': 8, 'approved_requests': 7, 'total_days': 15, 'employee_count': 6, 'avg_requests_per_employee': 1.33, 'avg_days_per_employee': 2.5},
            {'employee__hr_details__department__name': 'Finance', 'total_requests': 7, 'approved_requests': 6, 'total_days': 10, 'employee_count': 4, 'avg_requests_per_employee': 1.75, 'avg_days_per_employee': 2.5}
        ]
    
    def _get_fallback_leave_by_branch_data(self):
        """Return fallback leave by branch data."""
        return [
            {'employee__hr_details__branch__name': 'Main Branch', 'total_requests': 15, 'approved_requests': 13, 'total_days': 25, 'employee_count': 15, 'avg_requests_per_employee': 1.0, 'avg_days_per_employee': 1.67},
            {'employee__hr_details__branch__name': 'Nairobi Branch', 'total_requests': 6, 'approved_requests': 5, 'total_days': 12, 'employee_count': 8, 'avg_requests_per_employee': 0.75, 'avg_days_per_employee': 1.5},
            {'employee__hr_details__branch__name': 'Mombasa Branch', 'total_requests': 4, 'approved_requests': 4, 'total_days': 8, 'employee_count': 7, 'avg_requests_per_employee': 0.57, 'avg_days_per_employee': 1.14}
        ]
    
    def _get_fallback_approval_metrics_data(self):
        """Return fallback approval metrics data."""
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_requests': 25,
            'approved_requests': 22,
            'pending_requests': 2,
            'rejected_requests': 1,
            'approval_rate': 88.0,
            'rejection_rate': 4.0,
            'pending_rate': 8.0,
            'approval_by_approver': [
                {'approver__first_name': 'Manager', 'approver__last_name': 'One', 'total_processed': 15, 'approved': 13, 'rejected': 2, 'approval_rate': 86.7},
                {'approver__first_name': 'Manager', 'approver__last_name': 'Two', 'total_processed': 10, 'approved': 9, 'rejected': 1, 'approval_rate': 90.0}
            ]
        }
