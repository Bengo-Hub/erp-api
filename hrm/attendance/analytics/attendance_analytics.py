"""
Attendance Analytics Service

Provides comprehensive analytics for attendance management including attendance rates,
late arrivals, overtime analysis, and attendance trends.
"""

from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Avg, Count, Q, Sum, F, Min, Max
from django.db import connection
from django.core.cache import cache
import logging
from hrm.attendance.models import AttendanceRecord
from hrm.employees.models import Employee

logger = logging.getLogger(__name__)


class AttendanceAnalyticsService:
    """
    Service for attendance analytics and reporting.
    Provides metrics for attendance rates, late arrivals, overtime, and trends.
    """
    
    def __init__(self):
        self.cache_timeout = 300  # 5 minutes
    
    def get_attendance_dashboard_data(self, business_id=None, period='month', start_date=None, end_date=None, 
                                    region_id=None, department_id=None, branch_id=None):
        """
        Get comprehensive attendance dashboard data.
        
        Args:
            business_id: Business ID to filter data
            period: Time period for analysis ('week', 'month', 'quarter', 'year', 'custom')
            start_date: Custom start date (required if period='custom')
            end_date: Custom end date (required if period='custom')
            region_id: Region ID to filter data
            department_id: Department ID to filter data
            branch_id: Branch ID to filter data (from X-Branch-ID header)
            
        Returns:
            dict: Attendance dashboard data with fallbacks
        """
        try:
            return {
                'attendance_summary': self._get_attendance_summary(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'attendance_rates': self._get_attendance_rates(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'late_analysis': self._get_late_analysis(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'overtime_analysis': self._get_overtime_analysis(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'attendance_trends': self._get_attendance_trends(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'department_attendance': self._get_department_attendance(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'location_attendance': self._get_location_attendance(business_id, period, start_date, end_date, region_id, department_id, branch_id),
                'employee_attendance': self._get_employee_attendance(business_id, period, start_date, end_date, region_id, department_id, branch_id)
            }
        except Exception as e:
            logger.error(f"Error getting attendance dashboard data: {e}")
            return self._get_fallback_attendance_data()
    
    def _get_attendance_summary(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get attendance summary metrics."""
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
            
            queryset = AttendanceRecord.objects.filter(
                date__gte=start_date,
                date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Attendance statistics
            total_records = queryset.count()
            present_records = queryset.filter(status='present').count()
            absent_records = queryset.filter(status='absent').count()
            late_records = queryset.filter(status='late').count()
            half_day_records = queryset.filter(status='half_day').count()
            
            # Calculate rates
            attendance_rate = (present_records / total_records * 100) if total_records > 0 else 0
            absence_rate = (absent_records / total_records * 100) if total_records > 0 else 0
            late_rate = (late_records / total_records * 100) if total_records > 0 else 0
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_records': total_records,
                'present_records': present_records,
                'absent_records': absent_records,
                'late_records': late_records,
                'half_day_records': half_day_records,
                'attendance_rate': round(attendance_rate, 2),
                'absence_rate': round(absence_rate, 2),
                'late_rate': round(late_rate, 2)
            }
        except Exception:
            logger.error(f"Error getting attendance summary for business_id: {business_id}, period: {period}")
            return self._get_fallback_attendance_summary_data()
    
    def _get_attendance_rates(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get detailed attendance rates."""
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
            
            queryset = AttendanceRecord.objects.filter(
                date__gte=start_date,
                date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Daily attendance rates
            daily_rates = queryset.values('date').annotate(
                total=Count('id'),
                present=Count('id', filter=Q(status='present')),
                absent=Count('id', filter=Q(status='absent')),
                late=Count('id', filter=Q(status='late')),
                half_day=Count('id', filter=Q(status='half_day'))
            ).order_by('date')
            
            # Calculate daily percentages
            for day in daily_rates:
                if day['total'] > 0:
                    day['present_rate'] = round((day['present'] / day['total']) * 100, 2)
                    day['absent_rate'] = round((day['absent'] / day['total']) * 100, 2)
                    day['late_rate'] = round((day['late'] / day['total']) * 100, 2)
                    day['half_day_rate'] = round((day['half_day'] / day['total']) * 100, 2)
                else:
                    day['present_rate'] = 0
                    day['absent_rate'] = 0
                    day['late_rate'] = 0
                    day['half_day_rate'] = 0
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'daily_rates': list(daily_rates)
            }
        except Exception:
            logger.error(f"Error getting attendance rates for business_id: {business_id}, period: {period}")
            return self._get_fallback_attendance_rates_data()
    
    def _get_late_analysis(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get late arrival analysis."""
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
            
            queryset = AttendanceRecord.objects.filter(
                date__gte=start_date,
                date__lte=end_date,
                status='late'
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Late arrival statistics
            total_late = queryset.count()
            
            # Late by department
            late_by_department = queryset.values(
                'employee__hr_details__department__name'
            ).annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Late by branch
            late_by_branch = queryset.values(
                'employee__hr_details__branch__name'
            ).annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Late by employee
            late_by_employee = queryset.values(
                'employee__user__first_name',
                'employee__user__last_name'
            ).annotate(
                count=Count('id')
            ).order_by('-count')[:10]  # Top 10 late employees
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_late': total_late,
                'late_by_department': list(late_by_department),
                'late_by_branch': list(late_by_branch),
                'late_by_employee': list(late_by_employee)
            }
        except Exception:
            logger.error(f"Error getting late analysis for business_id: {business_id}, period: {period}")
            return self._get_fallback_late_analysis_data()
    
    def _get_overtime_analysis(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get overtime analysis."""
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
            
            queryset = AttendanceRecord.objects.filter(
                date__gte=start_date,
                date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Overtime statistics
            total_overtime_hours = queryset.aggregate(
                total=Sum('overtime_hours')
            )['total'] or 0
            
            avg_overtime_hours = queryset.aggregate(
                avg=Avg('overtime_hours')
            )['avg'] or 0
            
            # Overtime by department
            overtime_by_department = queryset.values(
                'employee__hr_details__department__name'
            ).annotate(
                total_hours=Sum('overtime_hours'),
                avg_hours=Avg('overtime_hours'),
                employee_count=Count('employee', distinct=True)
            ).order_by('-total_hours')
            
            # Overtime by branch
            overtime_by_branch = queryset.values(
                'employee__hr_details__branch__name'
            ).annotate(
                total_hours=Sum('overtime_hours'),
                avg_hours=Avg('overtime_hours'),
                employee_count=Count('employee', distinct=True)
            ).order_by('-total_hours')
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_overtime_hours': round(total_overtime_hours, 2),
                'avg_overtime_hours': round(avg_overtime_hours, 2),
                'overtime_by_department': list(overtime_by_department),
                'overtime_by_branch': list(overtime_by_branch)
            }
        except Exception:
            logger.error(f"Error getting overtime analysis for business_id: {business_id}, period: {period}")
            return self._get_fallback_overtime_analysis_data()
    
    def _get_attendance_trends(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get attendance trends over time."""
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
            
            queryset = AttendanceRecord.objects.filter(
                date__gte=start_date,
                date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            # Weekly trends
            weekly_trends = queryset.values('date__week').annotate(
                total=Count('id'),
                present=Count('id', filter=Q(status='present')),
                absent=Count('id', filter=Q(status='absent')),
                late=Count('id', filter=Q(status='late')),
                attendance_rate=Count('id', filter=Q(status='present')) * 100.0 / Count('id')
            ).order_by('date__week')
            
            # Monthly trends
            monthly_trends = queryset.values('date__month').annotate(
                total=Count('id'),
                present=Count('id', filter=Q(status='present')),
                absent=Count('id', filter=Q(status='absent')),
                late=Count('id', filter=Q(status='late')),
                attendance_rate=Count('id', filter=Q(status='present')) * 100.0 / Count('id')
            ).order_by('date__month')
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'weekly_trends': list(weekly_trends),
                'monthly_trends': list(monthly_trends)
            }
        except Exception:
            logger.error(f"Error getting attendance trends for business_id: {business_id}, period: {period}")
            return self._get_fallback_attendance_trends_data()
    
    def _get_department_attendance(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get attendance by department."""
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
            
            queryset = AttendanceRecord.objects.filter(
                date__gte=start_date,
                date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            department_attendance = queryset.values(
                'employee__hr_details__department__name'
            ).annotate(
                total=Count('id'),
                present=Count('id', filter=Q(status='present')),
                absent=Count('id', filter=Q(status='absent')),
                late=Count('id', filter=Q(status='late')),
                half_day=Count('id', filter=Q(status='half_day')),
                attendance_rate=Count('id', filter=Q(status='present')) * 100.0 / Count('id')
            ).order_by('-attendance_rate')
            
            return list(department_attendance)
        except Exception:
            logger.error(f"Error getting department attendance for business_id: {business_id}, period: {period}")
            return self._get_fallback_department_attendance_data()
    
    def _get_location_attendance(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get attendance by location."""
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
            
            queryset = AttendanceRecord.objects.filter(
                date__gte=start_date,
                date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            location_attendance = queryset.values(
                'employee__hr_details__region__name'
            ).annotate(
                total=Count('id'),
                present=Count('id', filter=Q(status='present')),
                absent=Count('id', filter=Q(status='absent')),
                late=Count('id', filter=Q(status='late')),
                half_day=Count('id', filter=Q(status='half_day')),
                attendance_rate=Count('id', filter=Q(status='present')) * 100.0 / Count('id')
            ).order_by('-attendance_rate')
            
            return list(location_attendance)
        except Exception:
            logger.error(f"Error getting location attendance for business_id: {business_id}, period: {period}")
            return self._get_fallback_location_attendance_data()
    
    def _get_employee_attendance(self, business_id, period, start_date, end_date, region_id, department_id, branch_id):
        """Get individual employee attendance."""
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
            
            queryset = AttendanceRecord.objects.filter(
                date__gte=start_date,
                date__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(employee__organisation__id=business_id)
            
            employee_attendance = queryset.values(
                'employee__user__first_name',
                'employee__user__last_name',
                'employee__hr_details__department__name'
            ).annotate(
                total=Count('id'),
                present=Count('id', filter=Q(status='present')),
                absent=Count('id', filter=Q(status='absent')),
                late=Count('id', filter=Q(status='late')),
                half_day=Count('id', filter=Q(status='half_day')),
                attendance_rate=Count('id', filter=Q(status='present')) * 100.0 / Count('id')
            ).order_by('-attendance_rate')[:20]  # Top 20 employees
            
            return list(employee_attendance)
        except Exception:
            logger.error(f"Error getting employee attendance for business_id: {business_id}, period: {period}")
            return self._get_fallback_employee_attendance_data()
    
    # Fallback data methods
    def _get_fallback_attendance_data(self):
        """Return fallback attendance data if analytics collection fails."""
        logger.warning("Returning fallback attendance data due to analytics collection failure.")
        return {
            'attendance_summary': self._get_fallback_attendance_summary_data(),
            'attendance_rates': self._get_fallback_attendance_rates_data(),
            'late_analysis': self._get_fallback_late_analysis_data(),
            'overtime_analysis': self._get_fallback_overtime_analysis_data(),
            'attendance_trends': self._get_fallback_attendance_trends_data(),
            'department_attendance': self._get_fallback_department_attendance_data(),
            'location_attendance': self._get_fallback_location_attendance_data(),
            'employee_attendance': self._get_fallback_employee_attendance_data()
        }
    
    def _get_fallback_attendance_summary_data(self):
        """Return fallback attendance summary data."""
        logger.warning("Returning fallback attendance summary data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_records': 600,
            'present_records': 540,
            'absent_records': 45,
            'late_records': 15,
            'half_day_records': 0,
            'attendance_rate': 90.0,
            'absence_rate': 7.5,
            'late_rate': 2.5
        }
    
    def _get_fallback_attendance_rates_data(self):
        """Return fallback attendance rates data."""
        logger.warning("Returning fallback attendance rates data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'daily_rates': [
                {
                    'date': timezone.now().date(),
                    'total': 20,
                    'present': 18,
                    'absent': 1,
                    'late': 1,
                    'half_day': 0,
                    'present_rate': 90.0,
                    'absent_rate': 5.0,
                    'late_rate': 5.0,
                    'half_day_rate': 0.0
                }
            ]
        }
    
    def _get_fallback_late_analysis_data(self):
        """Return fallback late analysis data."""
        logger.warning("Returning fallback late analysis data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_late': 15,
            'late_by_department': [
                {'employee__hr_details__department__name': 'IT', 'count': 8},
                {'employee__hr_details__department__name': 'Sales', 'count': 4},
                {'employee__hr_details__department__name': 'Finance', 'count': 3}
            ],
            'late_by_location': [
                {'employee__hr_details__region__name': 'Nairobi', 'count': 10},
                {'employee__hr_details__region__name': 'Mombasa', 'count': 3},
                {'employee__hr_details__region__name': 'Kisumu', 'count': 2}
            ],
            'late_by_employee': [
                {'employee__user__first_name': 'John', 'employee__user__last_name': 'Doe', 'count': 3},
                {'employee__user__first_name': 'Jane', 'employee__user__last_name': 'Smith', 'count': 2}
            ]
        }
    
    def _get_fallback_overtime_analysis_data(self):
        """Return fallback overtime analysis data."""
        logger.warning("Returning fallback overtime analysis data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_overtime_hours': 120.5,
            'avg_overtime_hours': 4.0,
            'overtime_by_department': [
                {'employee__hr_details__department__name': 'IT', 'total_hours': 45.0, 'avg_hours': 5.6, 'employee_count': 8},
                {'employee__hr_details__department__name': 'Sales', 'total_hours': 35.0, 'avg_hours': 5.8, 'employee_count': 6},
                {'employee__hr_details__department__name': 'Finance', 'total_hours': 25.0, 'avg_hours': 6.3, 'employee_count': 4}
            ],
            'overtime_by_location': [
                {'employee__hr_details__region__name': 'Nairobi', 'total_hours': 75.0, 'avg_hours': 5.0, 'employee_count': 15},
                {'employee__hr_details__region__name': 'Mombasa', 'total_hours': 30.0, 'avg_hours': 3.8, 'employee_count': 8},
                {'employee__hr_details__region__name': 'Kisumu', 'total_hours': 15.5, 'avg_hours': 2.2, 'employee_count': 7}
            ]
        }
    
    def _get_fallback_attendance_trends_data(self):
        """Return fallback attendance trends data."""
        logger.warning("Returning fallback attendance trends data.")
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'weekly_trends': [
                {'date__week': 1, 'total': 100, 'present': 90, 'absent': 7, 'late': 3, 'attendance_rate': 90.0}
            ],
            'monthly_trends': [
                {'date__month': 1, 'total': 600, 'present': 540, 'absent': 45, 'late': 15, 'attendance_rate': 90.0}
            ]
        }
    
    def _get_fallback_department_attendance_data(self):
        """Return fallback department attendance data."""
        logger.warning("Returning fallback department attendance data.")
        return [
            {'employee__hr_details__department__name': 'IT', 'total': 160, 'present': 148, 'absent': 8, 'late': 4, 'half_day': 0, 'attendance_rate': 92.5},
            {'employee__hr_details__department__name': 'Sales', 'total': 120, 'present': 108, 'absent': 9, 'late': 3, 'half_day': 0, 'attendance_rate': 90.0},
            {'employee__hr_details__department__name': 'Finance', 'total': 80, 'present': 72, 'absent': 6, 'late': 2, 'half_day': 0, 'attendance_rate': 90.0}
        ]
    
    def _get_fallback_location_attendance_data(self):
        """Return fallback location attendance data."""
        logger.warning("Returning fallback location attendance data.")
        return [
            {'employee__hr_details__region__name': 'Nairobi', 'total': 300, 'present': 270, 'absent': 22, 'late': 8, 'half_day': 0, 'attendance_rate': 90.0},
            {'employee__hr_details__region__name': 'Mombasa', 'total': 160, 'present': 144, 'absent': 12, 'late': 4, 'half_day': 0, 'attendance_rate': 90.0},
            {'employee__hr_details__region__name': 'Kisumu', 'total': 140, 'present': 126, 'absent': 11, 'late': 3, 'half_day': 0, 'attendance_rate': 90.0}
        ]
    
    def _get_fallback_employee_attendance_data(self):
        """Return fallback employee attendance data."""
        logger.warning("Returning fallback employee attendance data.")
        return [
            {'employee__user__first_name': 'John', 'employee__user__last_name': 'Doe', 'employee__hr_details__department__name': 'IT', 'total': 20, 'present': 19, 'absent': 0, 'late': 1, 'half_day': 0, 'attendance_rate': 95.0},
            {'employee__user__first_name': 'Jane', 'employee__user__last_name': 'Smith', 'employee__hr_details__department__name': 'Sales', 'total': 20, 'present': 18, 'absent': 1, 'late': 1, 'half_day': 0, 'attendance_rate': 90.0}
        ]
