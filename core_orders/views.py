from django.shortcuts import render
from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from django_filters import rest_framework as filters
from django.db.models import Q, Sum
from .models import BaseOrder, OrderItem, OrderPayment
from .serializers import (
    BaseOrderSerializer, BaseOrderListSerializer,
    OrderItemSerializer, OrderPaymentSerializer
)
from core.decorators import apply_common_filters, require_business_and_branch_context


class BaseOrderFilter(filters.FilterSet):
    """Filter for BaseOrder"""
    order_type = filters.CharFilter(lookup_expr='icontains')
    status = filters.CharFilter(lookup_expr='icontains')
    payment_status = filters.CharFilter(lookup_expr='icontains')
    fulfillment_status = filters.CharFilter(lookup_expr='icontains')
    customer_name = filters.CharFilter(method='filter_customer_name')
    supplier_name = filters.CharFilter(method='filter_supplier_name')
    date_from = filters.DateFilter(field_name='created_at', lookup_expr='gte')
    date_to = filters.DateFilter(field_name='created_at', lookup_expr='lte')
    
    class Meta:
        model = BaseOrder
        fields = ['order_type', 'status', 'payment_status', 'fulfillment_status']
    
    def filter_customer_name(self, queryset, name, value):
        return queryset.filter(
            Q(customer__first_name__icontains=value) |
            Q(customer__last_name__icontains=value) |
            Q(customer__user__first_name__icontains=value) |
            Q(customer__user__last_name__icontains=value)
        )
    
    def filter_supplier_name(self, queryset, name, value):
        return queryset.filter(
            Q(supplier__first_name__icontains=value) |
            Q(supplier__last_name__icontains=value) |
            Q(supplier__user__first_name__icontains=value) |
            Q(supplier__user__last_name__icontains=value)
        )


class BaseOrderViewSet(viewsets.ModelViewSet):
    """ViewSet for BaseOrder model"""
    queryset = BaseOrder.objects.all()
    serializer_class = BaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = BaseOrderFilter
    
    @apply_common_filters
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def get_serializer_class(self):
        if self.action == 'list':
            return BaseOrderListSerializer
        return BaseOrderSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Apply business and branch filters if available
        if hasattr(self.request, 'filters'):
            filters = self.request.filters
            if filters.get('business_id'):
                queryset = queryset.filter(customer__business_id=filters['business_id'])
            if filters.get('branch_id'):
                queryset = queryset.filter(branch_id=filters['branch_id'])
            if filters.get('region_id'):
                queryset = queryset.filter(branch__location__region_id=filters['region_id'])
            if filters.get('department_id'):
                # Orders don't have direct department, but can filter by customer's department
                queryset = queryset.filter(customer__hr_details__department_id=filters['department_id'])
        
        # If user is not superuser, filter by their orders
        if not user.is_superuser:
            queryset = queryset.filter(
                Q(customer__user=user) | Q(supplier__user=user) | Q(created_by=user)
            )
        
        return queryset.select_related('customer', 'supplier', 'created_by', 'branch', 'branch__location')
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an order if it's still in a cancellable state"""
        order = self.get_object()
        
        if order.status not in ['pending', 'confirmed']:
            return Response(
                {'error': 'Order cannot be cancelled in its current state'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        order.status = 'cancelled'
        order.save()
        
        return Response({'status': 'Order cancelled successfully'})
    
    @action(detail=True, methods=['post'])
    def mark_as_paid(self, request, pk=None):
        """Mark an order as paid"""
        order = self.get_object()
        order.payment_status = 'paid'
        order.save()
        
        return Response({'status': 'Order marked as paid'})
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get order summary statistics"""
        queryset = self.get_queryset()
        
        summary = {
            'total_orders': queryset.count(),
            'total_value': queryset.aggregate(total=Sum('total'))['total'] or 0,
            'pending_orders': queryset.filter(status='pending').count(),
            'completed_orders': queryset.filter(status='completed').count(),
            'cancelled_orders': queryset.filter(status='cancelled').count(),
        }
        
        return Response(summary)


class OrderItemViewSet(viewsets.ModelViewSet):
    """ViewSet for OrderItem model"""
    queryset = OrderItem.objects.all()
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # If user is not superuser, filter by their orders
        if not user.is_superuser:
            queryset = queryset.filter(
                Q(order__customer__user=user) | 
                Q(order__supplier__user=user) | 
                Q(order__created_by=user)
            )
        
        return queryset.select_related('order', 'content_type')
    
    def perform_create(self, serializer):
        # Calculate total price
        item = serializer.save()
        item.total_price = item.quantity * item.unit_price
        item.save()
        
        # Update order totals
        order = item.order
        order.update_order_amount()
    
    @action(detail=True, methods=['post'])
    def fulfill(self, request, pk=None):
        """Mark an order item as fulfilled"""
        item = self.get_object()
        fulfilled_quantity = request.data.get('fulfilled_quantity', item.quantity)
        
        if fulfilled_quantity > item.quantity:
            return Response(
                {'error': 'Fulfilled quantity cannot exceed ordered quantity'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        item.fulfilled_quantity = fulfilled_quantity
        item.is_fulfilled = fulfilled_quantity >= item.quantity
        item.save()
        
        return Response({'status': 'Item fulfillment updated'})


class OrderPaymentViewSet(viewsets.ModelViewSet):
    """ViewSet for OrderPayment model"""
    queryset = OrderPayment.objects.all()
    serializer_class = OrderPaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # If user is not superuser, filter by their orders
        if not user.is_superuser:
            queryset = queryset.filter(
                Q(order__customer__user=user) | 
                Q(order__supplier__user=user) | 
                Q(order__created_by=user)
            )
        
        return queryset.select_related('order', 'payment')
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        
        # Update order payment status
        order = serializer.instance.order
        total_paid = order.orderpayments.aggregate(
            total=Sum('payment__amount')
        )['total'] or 0
        
        if total_paid >= order.total:
            order.payment_status = 'paid'
        elif total_paid > 0:
            order.payment_status = 'partial'
        else:
            order.payment_status = 'pending'
        
        order.save()
