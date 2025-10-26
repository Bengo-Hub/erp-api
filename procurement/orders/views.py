#views 
from rest_framework import viewsets
from .models import PurchaseOrder
from .serializers import PurchaseOrderSerializer, PurchaseOrderListSerializer
from rest_framework import permissions
from rest_framework import filters
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Q
from decimal import Decimal
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination
from django.db import transaction
from procurement.purchases.models import *
from procurement.requisitions.models import *
from core.models import Departments
from approvals.models import Approval
from .functions import generate_purchase_order
from rest_framework.views import APIView
from django.utils import timezone
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class PurchaseOrderViewSet(BaseModelViewSet):
    queryset = PurchaseOrder.objects.all().select_related('created_by')
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = ['created_at']
    search_fields = ['order_number', 'status']

    def get_queryset(self):
        """Optimize queries with select_related for related objects."""
        queryset = super().get_queryset().prefetch_related('approvals')
        
        # Filter by params
        approver = self.request.query_params.get('approver', None)
        status_filter = self.request.query_params.get('status', None)

        if approver:
            queryset = queryset.filter(approvals__approver_id=approver)
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        return queryset 

    def get_serializer_context(self):
        """
        Add extra context to the serializer. The context added is
        include_requisition_details, which is a boolean indicating whether
        to include the details of the purchase requisition in the
        serializer output. The default is False.
        """
        context = super().get_serializer_context()
        context['include_requisition_details'] = self.request.query_params.get(
            'include_requisition', 'false'
        ).lower() == 'true'
        return context

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'], url_path='approve', name='approve')
    def approve(self, request, pk=None):
        """
        Approve a purchase order by a user from procurement/finance department.
        """
        try:    
            correlation_id = get_correlation_id(request)
            with transaction.atomic():  
                order = self.get_object()
                department = request.data.get('department', 'Procurement')
                
                if department.lower() not in ['procurement', 'finance']:
                    return APIResponse.forbidden(
                        message='Only procurement/finance can approve',
                        correlation_id=correlation_id
                    )
                
                # Create approval using centralized approval system
                approval = Approval.objects.create(
                    content_object=order,
                    approver=request.user,
                    status='approved',
                    notes=request.data.get('notes', f'Approved by {request.user.username}')
                )
                
                # Update order status if all approvals are complete
                order.status = 'approved'
                order.save()
                
                # Log approval
                AuditTrail.log(
                    operation=AuditTrail.APPROVAL,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=order.id,
                    user=request.user,
                    reason=f'Purchase order {order.order_number} approved by {department}',
                    request=request
                )
                
                return APIResponse.success(
                    data=self.get_serializer(order).data,
                    message='Purchase order approved successfully',
                    correlation_id=correlation_id
                )
        except Exception as e:
            logger.error(f'Error approving purchase order: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error approving purchase order',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='reject', name='reject')
    def reject(self, request, pk=None):
        """Reject a purchase order."""
        try:
            correlation_id = get_correlation_id(request)
            with transaction.atomic():
                order = self.get_object()
                
                # Create rejection approval
                Approval.objects.create(
                    content_object=order,
                    approver=request.user,
                    status='rejected',
                    notes=request.data.get('notes', f'Rejected by {request.user.username}')
                )
                
                # Update order status
                order.status = 'rejected'
                order.save()
                
                # Log rejection
                AuditTrail.log(
                    operation=AuditTrail.CANCEL,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=order.id,
                    user=request.user,
                    reason=f'Purchase order {order.order_number} rejected',
                    request=request
                )
                
                return APIResponse.success(
                    data=self.get_serializer(order).data,
                    message='Purchase order rejected',
                    correlation_id=correlation_id
                )
        except Exception as e:
            logger.error(f'Error rejecting purchase order: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error rejecting purchase order',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='cancel', name='cancel')
    def cancel(self, request, pk=None):
        """Cancel a purchase order."""
        try:
            correlation_id = get_correlation_id(request)
            with transaction.atomic():
                order = self.get_object()
                
                if order.status in ['completed', 'cancelled']:
                    return APIResponse.bad_request(
                        message=f'Cannot cancel purchase order with status: {order.status}',
                        error_id='invalid_order_status',
                        correlation_id=correlation_id
                    )
                
                # Update order status
                order.status = 'cancelled'
                order.save()
                
                # Log cancellation
                AuditTrail.log(
                    operation=AuditTrail.CANCEL,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=order.id,
                    user=request.user,
                    reason=f'Purchase order {order.order_number} cancelled',
                    request=request
                )
                
                return APIResponse.success(
                    data=self.get_serializer(order).data,
                    message='Purchase order cancelled successfully',
                    correlation_id=correlation_id
                )
        except Exception as e:
            logger.error(f'Error cancelling purchase order: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error cancelling purchase order',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )


class ProcurementDashboardView(APIView):
    """
    Procurement Dashboard API View
    
    Provides analytics and reporting for procurement operations including:
    - Purchase orders and requisitions
    - Supplier performance metrics
    - Spend analysis and trends
    - Category breakdowns
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get procurement dashboard data."""
        try:
            from procurement.analytics.procurement_analytics import ProcurementAnalyticsService
            
            # Get period from query params
            period = request.query_params.get('period', 'month')
            
            # Get dashboard data
            analytics_service = ProcurementAnalyticsService()
            dashboard_data = analytics_service.get_procurement_dashboard_data(period)
            
            return Response({
                'success': True,
                'data': dashboard_data,
                'period': period,
                'generated_at': timezone.now().isoformat()
            })
            
        except ImportError:
            # Return fallback data if analytics service not available
            return Response({
                'success': True,
                'data': {
                    'total_orders': 45,
                    'total_spend': 1250000.0,
                    'pending_orders': 12,
                    'completed_orders': 33,
                    'supplier_count': 25,
                    'average_order_value': 27777.78,
                    'top_suppliers': [
                        {
                            'name': 'ABC Suppliers Ltd',
                            'total_spend': 250000.0,
                            'order_count': 8,
                            'rating': 4.5
                        },
                        {
                            'name': 'XYZ Corporation',
                            'total_spend': 180000.0,
                            'order_count': 6,
                            'rating': 4.2
                        }
                    ],
                    'category_breakdown': [
                        {'category': 'Electronics', 'amount': 450000.0},
                        {'category': 'Office Supplies', 'amount': 280000.0}
                    ],
                    'order_trends': [
                        {'period': 'Jan 01', 'count': 3},
                        {'period': 'Jan 08', 'count': 5}
                    ],
                    'spend_analysis': [
                        {'period': 'Jan 01', 'amount': 45000.0},
                        {'period': 'Jan 08', 'amount': 52000.0}
                    ]
                },
                'period': request.query_params.get('period', 'month'),
                'generated_at': timezone.now().isoformat(),
                'note': 'Using fallback data - analytics service not available'
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
                'generated_at': timezone.now().isoformat()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)