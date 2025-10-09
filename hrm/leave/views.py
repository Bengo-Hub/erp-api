from datetime import datetime, timedelta
import logging
from django.shortcuts import render
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from .analytics.leave_analytics import LeaveAnalyticsService
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from .models import LeaveCategory, LeaveEntitlement, LeaveRequest, LeaveBalance, LeaveLog, PublicHoliday
from .serializers import (
    LeaveCategorySerializer,
    LeaveEntitlementSerializer,
    LeaveRequestSerializer,
    LeaveBalanceSerializer,
    LeaveLogSerializer,
    PublicHolidaySerializer,
)

# Create your views here.

class LeaveCategoryViewSet(viewsets.ModelViewSet):
    queryset = LeaveCategory.objects.all()
    serializer_class = LeaveCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']

class LeaveEntitlementViewSet(viewsets.ModelViewSet):
    queryset = LeaveEntitlement.objects.all()
    serializer_class = LeaveEntitlementSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        'employee': ['exact', 'in'],
        'category': ['exact', 'in'],
        'year': ['exact', 'gte', 'lte'],
        'days_entitled': ['exact', 'gte', 'lte'],
    }
    search_fields = ['employee__user__first_name', 'employee__user__last_name', 'category__name']

    def get_queryset(self):
        queryset = super().get_queryset()
        employee_ids = self.request.GET.get('employee_id')
        
        if employee_ids:
            employee_ids = employee_ids.split(',')
            queryset = queryset.filter(employee_id__in=employee_ids)
            
        return queryset.select_related('employee__user', 'category')

class LeaveRequestViewSet(viewsets.ModelViewSet):
    queryset = LeaveRequest.objects.all()
    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        'employee': ['exact', 'in'],
        'category': ['exact', 'in'],
        'status': ['exact', 'in'],
        'start_date': ['exact', 'gte', 'lte'],
        'end_date': ['exact', 'gte', 'lte'],
    }
    search_fields = [
        'employee__user__first_name', 
        'employee__user__last_name', 
        'category__name',
        'status',
        'description'
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.GET
        
        # Handle multiple employee IDs
        employee_ids = params.get('employee_id')
        if employee_ids:
            employee_ids = employee_ids.split(',')
            queryset = queryset.filter(employee_id__in=employee_ids)
        
        # Date range filtering
        start_date = params.get('start_date')
        end_date = params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(start_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(end_date__lte=end_date)
        
        # Category filtering
        category_id = params.get('category_id')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        
        # Status filtering
        status_value = params.get('status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        
        return queryset.select_related(
            'employee__user', 
            'category',
            'approved_by__user'
        ).order_by('-created_at')

    @action(detail=False, methods=['post'], url_path='validate')
    def validate_leave(self, request):
        """Validate leave request before submission"""
        try:
            data = request.data
            
            # Convert string dates to date objects
            try:
                start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            except (ValueError, KeyError) as e:
                return Response({
                    'error': 'Invalid date format. Use YYYY-MM-DD',
                    'valid': False
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate date range
            if start_date > end_date:
                return Response({
                    'error': 'End date must be after start date',
                    'valid': False
                }, status=status.HTTP_202_ACCEPTED)

            # Get employee and category IDs
            try:
                employee_id = int(data['employee_id'])
                category_id = int(data['category_id'])
            except (ValueError, KeyError) as e:
                return Response({
                    'error': 'Invalid employee_id or category_id',
                    'valid': False
                }, status=status.HTTP_202_ACCEPTED)

            # Calculate business days (excluding weekends and Kenyan public holidays)
            delta = end_date - start_date
            business_days = 0
            # Preload national public holidays in range
            holiday_dates = set(
                PublicHoliday.objects.filter(
                    is_national=True,
                    date__gte=start_date,
                    date__lte=end_date
                ).values_list('date', flat=True)
            )
            for i in range(delta.days + 1):
                day = start_date + timedelta(days=i)
                if day.weekday() < 5 and day not in holiday_dates:  # Monday=0, Sunday=6
                    business_days += 1
            
            # Check leave balance
            year = start_date.year
            balance = LeaveBalance.objects.filter(
                employee__id=employee_id,
                category__id=category_id,
                year=year
            ).first()
            
            if not balance:
                return Response({
                    'error': 'No leave entitlement found for this employee/category/year',
                    'valid': False
                }, status=status.HTTP_202_ACCEPTED)
            
            if balance.days_remaining < business_days:
                return Response({
                    'error': f'Insufficient leave balance. Available: {balance.days_remaining}, Requested: {business_days}',
                    'valid': False,
                    'available_days': balance.days_remaining,
                    'requested_days': business_days
                }, status=status.HTTP_202_ACCEPTED)
            
            return Response({
                'valid': True,
                'available_days': balance.days_remaining,
                'requested_days': business_days,
                'business_days': business_days,
                'calendar_days': (delta.days + 1)
            })
            
        except Exception as e:
            return Response({
                'error': f'An unexpected error occurred: {str(e)}',
                'valid': False
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        leave_request = self.get_object()
        if leave_request.status != 'pending':
            return Response(
                {'error': 'Leave request is not pending'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        leave_request.status = 'approved'
        # Safely set approved_by if employee exists
        try:
            if hasattr(request.user, 'employee'):
                leave_request.approved_by = request.user.employee
        except Exception as e:
            # Log the error but continue without setting approved_by
            logging.warning(f"Could not set approved_by: {str(e)}")
        leave_request.approved_at = timezone.now()
        leave_request.save()
        
        # Update leave balance
        leave_balance, created = LeaveBalance.objects.get_or_create(
            employee=leave_request.employee,
            category=leave_request.category,
            year=leave_request.start_date.year,
            defaults={
                'days_entitled': 0,
                'days_taken': 0,
                'days_remaining': 0
            }
        )
        
        leave_balance.days_taken += leave_request.days_requested
        leave_balance.days_remaining = leave_balance.days_entitled - leave_balance.days_taken
        leave_balance.save()
        
        return Response(self.get_serializer(leave_request).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        leave_request = self.get_object()
        
        # Check if leave is pending
        if leave_request.status != 'pending':
            return Response(
                {'error': 'Leave request is not pending'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check rejection reason
        rejection_reason = request.data.get('rejection_reason', '')
        if not rejection_reason:
            return Response(
                {'error': 'Rejection reason is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update leave request
        leave_request.status = 'rejected'
        leave_request.rejection_reason = rejection_reason
        
        # Safely set approved_by if employee exists
        try:
            if hasattr(request.user, 'employee'):
                leave_request.approved_by = request.user.employee
        except Exception as e:
            # Log the error but continue without setting approved_by
            logging.warning(f"Could not set approved_by: {str(e)}")
        
        leave_request.save()
        
        return Response(self.get_serializer(leave_request).data)

    @action(detail=False, methods=['post'], url_path='bulk_delete')
    def bulk_delete(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return Response(
                {'error': 'No leave requests selected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        deleted_count, _ = LeaveRequest.objects.filter(id__in=ids).delete()
        return Response(
            {'message': f'Successfully deleted {deleted_count} leave requests'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['post'], url_path='bulk_approve')
    def bulk_approve(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return Response(
                {'error': 'No leave requests selected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        leaves = LeaveRequest.objects.filter(id__in=ids, status='pending')
        approved_count = 0
        
        for leave in leaves:
            leave.status = 'approved'
            leave.approved_by = request.user.employee
            leave.approved_at = timezone.now()
            leave.save()
            
            # Update leave balance
            leave_balance, created = LeaveBalance.objects.get_or_create(
                employee=leave.employee,
                category=leave.category,
                year=leave.start_date.year,
                defaults={
                    'days_entitled': 0,
                    'days_taken': 0,
                    'days_remaining': 0
                }
            )
            
            leave_balance.days_taken += leave.days_requested
            leave_balance.days_remaining = leave_balance.days_entitled - leave_balance.days_taken
            leave_balance.save()
            
            approved_count += 1
        
        return Response(
            {'message': f'Successfully approved {approved_count} leave requests'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['post'], url_path='bulk_reject')
    def bulk_reject(self, request):
            ids = request.data.get('ids', [])
            rejection_reason = request.data.get('rejection_reason', '')
            
            if not ids:
                return Response(
                    {'error': 'No leave requests selected'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not rejection_reason:
                return Response(
                    {'error': 'Rejection reason is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            leaves = LeaveRequest.objects.filter(id__in=ids, status='pending')
            rejected_count = 0
            
            for leave in leaves:
                leave.status = 'rejected'
                leave.rejection_reason = rejection_reason
                leave.approved_by = request.user.employee
                leave.save()
                rejected_count += 1
            
            return Response(
                {'message': f'Successfully rejected {rejected_count} leave requests'},
                status=status.HTTP_200_OK
            )

class LeaveBalanceViewSet(viewsets.ModelViewSet):
    queryset = LeaveBalance.objects.all()
    serializer_class = LeaveBalanceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        'employee': ['exact', 'in'],
        'category': ['exact', 'in'],
        'year': ['exact', 'gte', 'lte'],
        'days_entitled': ['exact', 'gte', 'lte'],
        'days_taken': ['exact', 'gte', 'lte'],
        'days_remaining': ['exact', 'gte', 'lte'],
    }
    search_fields = [
        'employee__user__first_name',
        'employee__user__last_name',
        'category__name'
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Get filter parameters from request
        employee_id = self.request.GET.get('employee_id',None)
        category_id = self.request.GET.get('category_id',None)
        year = self.request.GET.get('year',None)
        
        # Apply filters
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if year:
            queryset = queryset.filter(year=year)
            
        return queryset.select_related('employee__user', 'category')

class LeaveLogViewSet(viewsets.ModelViewSet):
    queryset = LeaveLog.objects.all()
    serializer_class = LeaveLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        'leave_request__employee': ['exact', 'in'],
        'leave_request__category': ['exact', 'in'],
        'action': ['exact', 'in'],
        'created_at': ['exact', 'gte', 'lte'],
    }
    search_fields = [
        'leave_request__employee__user__first_name',
        'leave_request__employee__user__last_name',
        'leave_request__category__name',
        'description'
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.GET
        
        # Handle employee filter
        employee_id = params.get('employee_id')
        if employee_id:
            queryset = queryset.filter(leave_request__employee_id=employee_id)
        
        # Handle category filter
        category_id = params.get('category_id')
        if category_id:
            queryset = queryset.filter(leave_request__category_id=category_id)
        
        # Handle date filter
        date = params.get('date')
        if date:
            queryset = queryset.filter(created_at__date=date)
        
        return queryset.select_related(
            'leave_request__employee__user',
            'leave_request__category',
            'user'
        ).order_by('-created_at')


class PublicHolidayViewSet(viewsets.ModelViewSet):
    queryset = PublicHoliday.objects.all()
    serializer_class = PublicHolidaySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'county']
    filterset_fields = ['is_national', 'county', 'date']

    def get_queryset(self):
        return super().get_queryset().order_by('-date')


@api_view(['GET'])
def leave_analytics(request):
    """
    Get leave analytics data.
    """
    try:
        period = request.query_params.get('period', 'month')
        business_id = request.query_params.get('business_id')
        
        analytics_service = LeaveAnalyticsService()
        data = analytics_service.get_leave_dashboard_data(
            business_id=business_id,
            period=period
        )
        
        return Response({
            'success': True,
            'data': data,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error fetching leave analytics: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=500)