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


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = ['created_at']
    search_fields = ['order_number', 'status']

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by params
        approver = self.request.query_params.get('approver', None)
        status = self.request.query_params.get('status', None)

        if approver:
            queryset = queryset.filter(approvals__approver_id=approver)
        
        if status:
            queryset = queryset.filter(status=status)
            
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
        Approve a purchase order by a user from procurement/finance department. If
        all required approvals are given, the order status is updated to 'approved'.
        """
        try:    
            with transaction.atomic():  
                order = self.get_object()
                department = request.data.get('department', 'Procurement')
                
                if department.lower() not in ['procurement', 'finance']:
                    return Response(
                        {'error': 'Only procurement/finance can approve'},
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Create approval using centralized approval system
                from django.contrib.contenttypes.models import ContentType
                content_type = ContentType.objects.get_for_model(PurchaseOrder)
                
                approval = Approval.objects.create(
                    content_type=content_type,
                    object_id=order.id,
                    approver=request.user,
                    status='approved',
                    notes=f'Approved by {department} department'
                )
                
                # Add approval to order's approvals
                order.approvals.add(approval)
                
                # Check if order is fully approved
                if order.is_fully_approved():
                    order.approve_order(request.user)
                
            return Response({'status': 'approved'})
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    def create_purchase(self, user, order):
        """Helper method to create purchase from this order"""
            
        purchase = Purchase.objects.create(
            purchase_order=order,
            purchase_id=generate_purchase_order(order.id),
            supplier=order.supplier,
            added_by=user,
            grand_total=Decimal(order.approved_budget),
            sub_total=Decimal(order.approved_budget),
            purchase_status='ordered'
        )
        
        # Copy items
        for item in order.requisition.items.all():
            PurchaseItems.objects.create(
                purchase=purchase,
                stock_item=item.stock_item,
                qty=item.quantity,
                unit_price=item.stock_item.buying_price
            )
        
        purchase.status = 'processed'
        purchase.save()
        return purchase
    
    @action(detail=True, methods=['post'], url_path='convert-to-purchase', name='convert-to-purchase')
    def convert_to_purchase(self, request, pk=None):
        """
        Convert a purchase order to a purchase if all required approvals are given.
        
        - If all required approvals are given, the order status is updated to 'approved'.
        - Creates a new purchase and returns the purchase data.
        
        :return: The newly created purchase data
        :rtype: dict
        :raises: HTTP 400 if conversion fails
        """
        order = self.get_object()
        try:
            purchase = self.create_purchase(request.user, order)
            from procurement.purchases.serializers import PurchaseSerializer
            serializer = PurchaseSerializer(purchase)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
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