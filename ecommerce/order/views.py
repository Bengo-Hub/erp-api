from .models import Order
from core_orders.models import OrderItem, OrderPayment
from rest_framework.response import Response
from rest_framework import viewsets, status
from rest_framework import permissions
from rest_framework.decorators import action, api_view, permission_classes
from .serializers import OrderSerializer, OrderItemSerializer, OrderDetailSerializer
from rest_framework.pagination import PageNumberPagination
from crm.contacts.models import Contact
from ecommerce.cart.models import CartSession
from ecommerce.cart.serializers import CartSessionSerializer
from django.shortcuts import get_object_or_404
from django.db import transaction
from .checkout import CheckoutService
from django.http import HttpResponse
from finance.payment.services import get_payment_service
from finance.payment.models import BillingDocument
from finance.payment.pdf_utils import download_invoice_pdf
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class OrderViewSet(BaseModelViewSet):
    queryset = Order.objects.all().select_related('user')
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PageNumberPagination  # Standardized: 100 records per page

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # If user is not superuser, only return their orders
        if not user.is_superuser:
            queryset = queryset.filter(user=user)
            
        return queryset

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an order if it's still in a cancellable state"""
        try:
            correlation_id = get_correlation_id(request)
            order = self.get_object()
            
            # Check if order can be cancelled
            if order.status not in [Order.STATUS_PENDING, Order.STATUS_PROCESSING]:
                return APIResponse.bad_request(
                    message=f'Cannot cancel order in {order.get_status_display()} state',
                    error_id='invalid_status_for_cancellation',
                    correlation_id=correlation_id)
            
            with transaction.atomic():
                order.mark_as_cancelled(request.user, request.data.get('reason', ''))
                AuditTrail.log(operation=AuditTrail.CANCEL, module='ecommerce', entity_type='Order', entity_id=order.id, user=request.user, reason=f'Order cancelled: {request.data.get("reason", "")}', request=request)
            
            return APIResponse.success(data=self.get_serializer(order).data, message='Order cancelled successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error cancelling order: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error cancelling order', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get the history of an order"""
        try:
            correlation_id = get_correlation_id(request)
            order = self.get_object()
            history = [] # Placeholder for actual history data
            
            # Use a serializer for OrderHistory in a real implementation
            history_data = [{
                'status': item.status,
                'message': item.message,
                'created_at': item.created_at,
                'created_by': item.created_by.get_full_name() if item.created_by else 'System'
            } for item in history]
            
            data = {
                'order_id': order.order_id,
                'history': history_data
            }
            return APIResponse.success(data=data, message='Order history retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching order history: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving order history', error_id=str(e), correlation_id=get_correlation_id(request))
        
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update the status of an order (admin/staff only)"""
        try:
            correlation_id = get_correlation_id(request)
            # Check permissions - only staff/admin should update order status
            if not request.user.is_staff and not request.user.is_superuser:
                return APIResponse.forbidden(message='Only staff/admin can update order status', correlation_id=correlation_id)
            
            order = self.get_object()
            status_value = request.data.get('status')
            
            if not status_value:
                return APIResponse.bad_request(message='Status is required', error_id='missing_status', correlation_id=correlation_id)
            
            # Validate status is valid
            valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
            if status_value not in valid_statuses:
                return APIResponse.bad_request(message=f'Invalid status. Valid options: {", ".join(valid_statuses)}', error_id='invalid_status', correlation_id=correlation_id)
            
            old_status = order.status
            order.status = status_value
            order.save(update_fields=['status', 'updated_at'])
            
            AuditTrail.log(operation=AuditTrail.UPDATE, module='ecommerce', entity_type='Order', entity_id=order.id, user=request.user, changes={'status': {'old': old_status, 'new': status_value}}, reason=f'Order status updated to {status_value}', request=request)
            
            return APIResponse.success(data=self.get_serializer(order).data, message='Order status updated successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error updating order status: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error updating order status', error_id=str(e), correlation_id=get_correlation_id(request))


class OrderItemViewSet(BaseModelViewSet):
    queryset = OrderItem.objects.all().select_related('order')
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated,]
    pagination_class = PageNumberPagination  # Standardized: 100 records per page

    def get_queryset(self):
        queryset = super().get_queryset()
        # Apply filters based on query parameters
        user = self.request.user
        
        # Filter to only show order items from the user's orders or for staff
        if not user.is_staff and not user.is_superuser:
            queryset = queryset.filter(order__user=user)
        
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def checkout(request):
    """
    Checkout endpoint for registered customers to place orders
    Converts cart to order and optionally processes payment
    """
    user = request.user
    cart_id = request.data.get('cart_id')
    
    if not cart_id:
        # Use the user's active cart if no cart_id specified
        try:
            cart = CartSession.objects.get(user=user, is_active=True)
        except CartSession.DoesNotExist:
            return Response(
                {'status': 'failed', 'message': 'No active cart found'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        # Use the specified cart
        try:
            cart = CartSession.objects.get(id=cart_id, user=user)
        except CartSession.DoesNotExist:
            return Response(
                {'status': 'failed', 'message': f'Cart with ID {cart_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    # Initialize checkout service
    checkout_service = CheckoutService(cart=cart, user=user)
    
    try:
        # Process checkout with the provided data
        order, success, message = checkout_service.process_checkout(request.data)
        
        if not success:
            return Response(
                {'status': 'failed', 'message': message},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Return order details
        serializer = OrderSerializer(order)
        return Response({
            'status': 'success',
            'message': 'Order placed successfully',
            'order': serializer.data
        })
    except Exception as e:
        logger.exception(f"Checkout process failed: {str(e)}")
        return Response(
            {'status': 'failed', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def guest_checkout(request):
    """
    Guest checkout endpoint allowing customers to place orders without prior registration
    Silently creates a user account from the provided billing information
    """
    cart_session_key = request.data.get('cart_session_key')
    
    if not cart_session_key:
        return Response(
            {'status': 'failed', 'message': 'Cart session key is required for guest checkout'},
            status=status.HTTP_400_BAD_REQUEST
        )
        
    # Find the guest cart by session key
    try:
        cart = CartSession.objects.get(session_key=cart_session_key, is_active=True)
    except CartSession.DoesNotExist:
        return Response(
            {'status': 'failed', 'message': f'Cart with session key {cart_session_key} not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Validate that we have billing information
    if not request.data.get('billing_address'):
        return Response(
            {'status': 'failed', 'message': 'Billing address is required for guest checkout'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Initialize checkout service (user=None indicates guest checkout)
    checkout_service = CheckoutService(cart=cart, user=None)
    
    try:
        # Process checkout - this will create a user account from billing info
        order, success, message = checkout_service.process_checkout(request.data)
        
        if not success:
            return Response(
                {'status': 'failed', 'message': message},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Return order details - don't expose too much about the created account
        serializer = OrderSerializer(order)
        return Response({
            'status': 'success',
            'message': 'Order placed successfully. An account has been created for your convenience.',
            'order': serializer.data
        })
    except Exception as e:
        logger.exception(f"Guest checkout process failed: {str(e)}")
        return Response(
            {'status': 'failed', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_orders(request):
    """
    Get all orders for the logged-in customer
    Can be filtered by status
    """
    user = request.user
    status_filter = request.query_params.get('status')
    
    orders = Order.objects.filter(customer__user=user).order_by('-created_at')
    
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    serializer = OrderSerializer(orders, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_details(request, order_id):
    """
    Get detailed information about a specific order
    """
    user = request.user
    
    try:
        order = Order.objects.get(order_id=order_id, customer__user=user)
    except Order.DoesNotExist:
        return Response(
            {'status': 'failed', 'message': 'Order not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    serializer = OrderSerializer(order)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def track_order(request, order_id):
    """
    Get tracking information for a specific order
    """
    user = request.user
    
    # Verify that the order belongs to the logged-in user
    order = get_object_or_404(Order, order_id=order_id, customer__user=user)
    
    # Initialize tracking service
    from .tracking import OrderTrackingService
    tracking_service = OrderTrackingService(order=order)
    
    # Get tracking information
    tracking_info = tracking_service.get_tracking_info()
    
    return Response(tracking_info)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def cancel_order(request, order_id):
    """
    Cancel an order if it's in a cancellable state
    """
    user = request.user
    
    # Verify that the order belongs to the logged-in user
    order = get_object_or_404(Order, order_id=order_id, customer__user=user)
    
    # Check if order can be cancelled
    from .tracking import OrderTrackingService
    tracking_service = OrderTrackingService(order=order)
    if not tracking_service.can_cancel_order():
        return Response(
            {'status': 'failed', 'message': 'This order cannot be cancelled'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Process cancellation
    checkout_service = CheckoutService(cart=None, user=user)
    success, message = checkout_service.update_order_status(
        order_id=order_id,
        new_status='cancelled',
        user=user,
        notes=f"Order cancelled by customer: {request.data.get('reason', 'No reason provided')}"
    )
    
    if success:
        return Response({'status': 'success', 'message': 'Order cancelled successfully'})
    else:
        return Response(
            {'status': 'failed', 'message': message},
            status=status.HTTP_400_BAD_REQUEST
        )

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_order_payment(request, order_id):
    """
    Add payment to an existing order
    Supports:
    - Single payment method
    - Split payment with multiple methods
    """
    user = request.user
    
    # Verify that the order belongs to the logged-in user
    order = get_object_or_404(Order, order_id=order_id, customer__user=user)
    
    # Check if payment is needed
    if order.payment_status == 'paid':
        return Response(
            {'status': 'failed', 'message': 'This order is already fully paid'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Process payment using centralized payment service
    payment_service = get_payment_service()
    
    # Check if this is a split payment
    if request.data.get('is_split_payment'):
        # Format payment methods in the expected structure for the payment service
        payment_methods = []
        for payment in request.data.get('payments', []):
            payment_methods.append({
                'payment_method': payment.get('payment_method'),
                'amount': payment.get('amount'),
                'transaction_id': payment.get('transaction_id', ''),
                'transaction_details': payment.get('details', {})
            })
            
        success, message, _ = payment_service.process_split_payment(
            entity_type='order',
            entity_id=order_id,
            payments=payment_methods,
            created_by=user
        )
    else:
        # Process single payment
        amount = request.data.get('amount')
        payment_method = request.data.get('payment_method')
        transaction_id = request.data.get('transaction_id', '')
        transaction_details = request.data.get('details', {})
        
        success, message, _ = payment_service.process_order_payment(
            order=order,
            amount=amount,
            payment_method=payment_method,
            transaction_id=transaction_id,
            transaction_details=transaction_details,
            created_by=user
        )
    
    if success:
        # Refresh order data
        order.refresh_from_db()
        serializer = OrderSerializer(order)
        return Response({
            'status': 'success', 
            'message': 'Payment processed successfully',
            'order': serializer.data
        })
    else:
        return Response(
            {'status': 'failed', 'message': message},
            status=status.HTTP_400_BAD_REQUEST
        )


# Customer-facing views
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def download_order_invoice(request, order_id):
    """
    Generate and download an invoice PDF for an order
    """
    user = request.user
    
    # Verify that the order belongs to the logged-in user
    order = get_object_or_404(Order, order_id=order_id, customer__user=user)
    
    # Find associated billing document (invoice) for this order
    try:
        # Look for an invoice document related to this order
        invoice = BillingDocument.objects.get(
            related_order=order,
            document_type=BillingDocument.INVOICE
        )
    except BillingDocument.DoesNotExist:
        # No invoice found - order might not have a billing document yet
        return HttpResponse(
            "No invoice available for this order.",
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Generate PDF response using centralized billing module
    filename = f"Invoice_{order.order_id}_{invoice.document_number}.pdf"
    return download_invoice_pdf(invoice, filename=filename)
