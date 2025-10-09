from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import action
from django.db.models import Q
from decimal import Decimal
import logging

from ecommerce.stockinventory.functions import generate_ref_no
from .models import Purchase, PurchaseItems, PayTerm, StockInventory
from .serializers import *
from finance.payment.services import PaymentOrchestrationService
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()

class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all()
    serializer_class = PurchasesSerializer

    def create(self, request, *args, **kwargs):
       
        data = request.data
        purchase_items_data = data.pop('purhaseitems', [])  # Get purchase items data from the payload
        # Handle the pay term
        pay_term_data = data.pop('pay_term', None)
        if pay_term_data.get('pay_duration',0)>0:
            pay_term, _ = PayTerm.objects.get_or_create(
                duration=pay_term_data.get('pay_duration', 0),
                period=pay_term_data.get('duration_type', 'Days')
            )
            data['pay_term'] = pay_term.id
        data['pay_term'] = None
        #purchase id
        purchase_id=data.get("purchase_id",None)
        if purchase_id =='' or purchase_id is None:
            purchase_id=generate_ref_no("PO")
        data['purchase_id']=purchase_id
        # Serialize and validate the main Purchase data
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        
        # Save the main Purchase instance
        purchase = serializer.save()
        # Calculate balance due and overdue
        purchase.balance_due = max(purchase.grand_total - purchase.purchase_ammount, 0)
        purchase.balance_overdue = max(purchase.purchase_ammount - purchase.grand_total, 0)

        # Update stock levels if conditions are met
        if (purchase.purchase_status == 'received') and (purchase.payment_status in ['paid', 'partial']):
            for purchase_item in purchase.purchaseitems.all():
                stock_item = purchase_item.stock_item
                stock_item.stock_level += purchase_item.qty  # Increase stock level
                stock_item.save()

            # Update payment details
            purchase.purchase_ammount = purchase.grand_total
            purchase.balance_due = max(purchase.grand_total - purchase.purchase_ammount, 0)
            purchase.balance_overdue = max(purchase.purchase_ammount - purchase.grand_total, 0)

        # Save the purchase again with updated values
        purchase.save()

        # Save related PurchaseItems
        for item_data in purchase_items_data:
            product_data = item_data.pop('product', {})
            variation_data = item_data.pop('variation', {})
            
            # Create or fetch the related stock_item
            stock_item = StockInventory.objects.get(
                Q(product__sku=item_data.get('sku')) |
                Q(product_id=product_data.get('id')) |
                Q(variation__sku=variation_data.get('sku'))
            )
            
            # Add the stock_item reference to item_data
            item_data['stock'] = stock_item.id
            item_data['purchase'] = purchase.id
            _,_=PurchaseItems.objects.update_or_create(
                purchase=purchase,
                defaults={
                    "stock_item":stock_item,
                    "qty":item_data.get('quantity',0),
                    "discount_amount":item_data.get('discount_amount',0),
                    "unit_price":item_data.get('unit_price',0)
                }
            )

        # Return the full Purchase data with related items
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        """
        Handle the update of a Purchase instance and its related PurchaseItems.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        data = request.data
        purchase_items_data = data.pop('purhaseitems', [])

        # Serialize and validate the main Purchase data
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)

        # Save the main Purchase instance
        purchase = serializer.save()
        # Calculate balance due and overdue
        purchase.balance_due = max(purchase.grand_total - purchase.purchase_ammount, 0)
        purchase.balance_overdue = max(purchase.purchase_ammount - purchase.grand_total, 0)

        # Update stock levels if conditions are met
        if (purchase.purchase_status == 'received') and (purchase.payment_status in ['paid', 'partial']):
            for purchase_item in purchase.purchaseitems.all():
                stock_item = purchase_item.stock_item
                stock_item.stock_level += purchase_item.qty  # Increase stock level
                stock_item.save()

            # Update payment details
            purchase.purchase_ammount = purchase.grand_total
            purchase.balance_due = max(purchase.grand_total - purchase.purchase_ammount, 0)
            purchase.balance_overdue = max(purchase.purchase_ammount - purchase.grand_total, 0)

        # Save the purchase again with updated values
        purchase.save()

        # Update related PurchaseItems
        for item_data in purchase_items_data:
            product_data = item_data.pop('product', {})
            variation_data = item_data.pop('variation', {})
            
            # Find the existing stock_item
            stock_item = StockInventory.objects.get(
                sku=item_data.get('sku'),
                product_id=product_data.get('id'),
                variation__sku=variation_data.get('sku')
            )
            
            # Add the stock_item reference to item_data
            item_data['stock_item'] = stock_item.id
            item_data['purchase'] = purchase.id
            
            # Check if the item already exists or create a new one
            purchase_item = PurchaseItems.objects.filter(
                purchase=purchase,
                stock_item=stock_item
            ).first()
            
            if purchase_item:
                item_serializer = PurchaseItemSerializer(purchase_item, data=item_data, partial=partial)
            else:
                item_serializer = PurchaseItemSerializer(data=item_data)

            item_serializer.is_valid(raise_exception=True)
            item_serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)
    

    @action(detail=False, methods=['post'], url_path='from-order/(?P<order_id>\d+)')
    def create_from_order(self, request, order_id=None):
        """
        Create a purchase from an approved purchase order
        """
        try:
            order = PurchaseOrder.objects.get(id=order_id)
            
            # Validate order status
            if not order.approvals.filter(status='approved').exists():
                return Response(
                    {'error': 'Purchase order must be fully approved'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create purchase from order
            purchase_data = {
                'supplier': order.supplier.id,
                'purchase_order': order.id,
                'purchase_status': 'ordered',
                'payment_status': 'pending',
                'grand_total': order.approved_budget,
                'sub_total': order.approved_budget,
                'purchase_id': generate_ref_no("PO")
            }

            serializer = self.get_serializer(data=purchase_data)
            serializer.is_valid(raise_exception=True)
            purchase = serializer.save(added_by=request.user)

            # Convert order items to purchase items
            for item in order.requisition.items.all():
                PurchaseItems.objects.create(
                    purchase=purchase,
                    stock_item=item.stock_item,
                    qty=item.quantity,
                    unit_price=item.stock_item.buying_price,
                    sub_total=item.stock_item.buying_price * item.quantity
                )

            # Update order status
            order.status = 'processed'
            order.save()

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except PurchaseOrder.DoesNotExist:
            return Response(
                {'error': 'Purchase order not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['post'])
    def process_payment(self, request, pk=None):
        """Process payment for a purchase using centralized payment system"""
        try:
            purchase = self.get_object()
            amount = request.data.get('amount')
            payment_method = request.data.get('payment_method')
            transaction_details = request.data.get('transaction_details', {})

            if not all([amount, payment_method]):
                return Response({
                    'status': 'failed',
                    'message': 'Missing required parameters: amount, payment_method'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Use centralized payment service
            payment_service = PaymentOrchestrationService()
            success, message, payment = payment_service.process_purchase_payment(
                purchase=purchase,
                amount=Decimal(str(amount)),
                payment_method=payment_method,
                transaction_details=transaction_details,
                created_by=request.user
            )

            if success:
                return Response({
                    'status': 'success',
                    'message': 'Payment processed successfully',
                    'payment_id': payment.id if payment else None
                })
            else:
                return Response({
                    'status': 'failed',
                    'message': message
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error processing purchase payment: {str(e)}")
            return Response({
                'status': 'failed',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
