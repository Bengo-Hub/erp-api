from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from decimal import Decimal
import logging

from ecommerce.stockinventory.functions import generate_ref_no
from .models import Purchase, PurchaseItems, PayTerm, StockInventory
from .serializers import *
from finance.payment.services import PaymentOrchestrationService
from django.contrib.auth import get_user_model
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from core.utils import get_branch_id_from_request, get_business_id_from_request
from business.models import Branch

logger = logging.getLogger(__name__)
User = get_user_model()

class PurchaseViewSet(BaseModelViewSet):
    queryset = Purchase.objects.all().select_related('supplier', 'pay_term')
    serializer_class = PurchasesSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Optimize queries with select_related for related objects."""
        queryset = super().get_queryset()
        queryset = queryset.prefetch_related('purchaseitems__stock_item__product')

        try:
            branch_id = self.request.query_params.get('branch_id') or get_branch_id_from_request(self.request)
        except Exception:
            branch_id = None

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if not self.request.user.is_superuser:
            user = self.request.user
            owned_branches = Branch.objects.filter(business__owner=user)
            employee_branches = Branch.objects.filter(business__employees__user=user)
            branches = owned_branches | employee_branches
            queryset = queryset.filter(branch__in=branches)

        return queryset

    def create(self, request, *args, **kwargs):
        """Create purchase with validation, reference generation, and audit logging."""
        try:
            correlation_id = get_correlation_id(request)
            data = request.data.copy()
            # Read branch from header or payload
            try:
                header_branch_id = request.query_params.get('branch_id') or get_branch_id_from_request(request)
            except Exception:
                header_branch_id = None

            if header_branch_id:
                data['branch'] = header_branch_id
                # Validate branch access for non-superusers
                if not request.user.is_superuser:
                    owned_branches = Branch.objects.filter(business__owner=request.user)
                    employee_branches = Branch.objects.filter(business__employees__user=request.user)
                    allowed = owned_branches | employee_branches
                    if not allowed.filter(id=header_branch_id).exists():
                        return APIResponse.forbidden(message='Not allowed to create purchase for this branch', correlation_id=correlation_id)
            purchase_items_data = data.pop('purhaseitems', [])  # Get purchase items data from the payload
            
            # Validate purchase items
            if not purchase_items_data:
                return APIResponse.validation_error(
                    message='At least one purchase item is required',
                    errors={'purhaseitems': 'Cannot be empty'},
                    correlation_id=correlation_id
                )
            
            # Handle the pay term
            pay_term_data = data.pop('pay_term', None)
            if pay_term_data and pay_term_data.get('pay_duration', 0) > 0:
                pay_term, _ = PayTerm.objects.get_or_create(
                    duration=pay_term_data.get('pay_duration', 0),
                    period=pay_term_data.get('duration_type', 'Days')
                )
                data['pay_term'] = pay_term.id
            else:
                data['pay_term'] = None
            
            # Generate purchase ID if not provided
            purchase_id = data.get("purchase_id", None)
            if purchase_id == '' or purchase_id is None:
                purchase_id = generate_ref_no("PO")
            data['purchase_id'] = purchase_id
            
            # Serialize and validate the main Purchase data
            serializer = self.get_serializer(data=data)
            if not serializer.is_valid():
                return APIResponse.validation_error(
                    message='Purchase validation failed',
                    errors=serializer.errors,
                    correlation_id=correlation_id
                )
            
            # Save the main Purchase instance
            purchase = serializer.save()
            
            # Calculate balance due and overdue
            purchase.balance_due = max(purchase.grand_total - purchase.purchase_ammount, 0)
            purchase.balance_overdue = max(purchase.purchase_ammount - purchase.grand_total, 0)

            # Update stock levels if conditions are met
            if (purchase.purchase_status == 'received') and (purchase.payment_status in ['paid', 'partial']):
                for purchase_item in purchase.purchaseitems.all():
                    stock_item = purchase_item.stock_item
                    if not stock_item:
                        # Service or non-stock item
                        continue
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
                
                try:
                    # Create or fetch the related stock_item
                    stock_item = StockInventory.objects.get(
                        Q(product__sku=item_data.get('sku')) |
                        Q(product_id=product_data.get('id')) |
                        Q(variation__sku=variation_data.get('sku'))
                    )
                    
                    # Add the stock_item reference to item_data
                    item_data['stock_item'] = stock_item.id
                    item_data['purchase'] = purchase.id
                    PurchaseItems.objects.update_or_create(
                        purchase=purchase,
                        defaults={
                            "stock_item": stock_item,
                                "product": None,
                            "qty": item_data.get('quantity', 0),
                            "discount_amount": item_data.get('discount_amount', 0),
                            "unit_price": item_data.get('unit_price', 0)
                        }
                    )
                except StockInventory.DoesNotExist:
                    # Not a stock item, try resolving product id (for service items)
                    product_id = product_data.get('id') or item_data.get('product_id')
                    if product_id:
                        from ecommerce.product.models import Products as ProductModel
                        product_obj = ProductModel.objects.filter(id=product_id).first()
                        if product_obj:
                            # Create PurchaseItems referencing product (e.g., services)
                            PurchaseItems.objects.update_or_create(
                                purchase=purchase,
                                product=product_obj,
                                defaults={
                                    "stock_item": None,
                                    "qty": item_data.get('quantity', 0),
                                    "discount_amount": item_data.get('discount_amount', 0),
                                    "unit_price": item_data.get('unit_price', product_obj.default_price)
                                }
                            )
                            continue
                    logger.warning(f"Stock item and Product not found for purchase item: {item_data}")
                    continue

            # Log purchase creation
            AuditTrail.log(
                operation=AuditTrail.CREATE,
                module='procurement',
                entity_type='Purchase',
                entity_id=purchase.id,
                user=request.user,
                changes={'purchase_id': {'new': purchase.purchase_id}},
                reason=f'Created purchase {purchase.purchase_id}',
                request=request
            )

            return APIResponse.created(
                data=self.get_serializer(purchase).data,
                message='Purchase created successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error creating purchase: {str(e)}', exc_info=True)
            correlation_id = get_correlation_id(request)
            return APIResponse.server_error(
                message='Error creating purchase',
                error_id=str(e),
                correlation_id=correlation_id
            )

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
                if not stock_item:
                    # Non-stock product/service
                    continue
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
            # Try to find the existing stock_item, else fallback to product
            stock_item = None
            product_obj = None
            try:
                stock_item = StockInventory.objects.get(
                    sku=item_data.get('sku'),
                    product_id=product_data.get('id'),
                    variation__sku=variation_data.get('sku')
                )
                item_data['stock_item'] = stock_item.id
            except StockInventory.DoesNotExist:
                product_id = product_data.get('id') or item_data.get('product_id')
                if product_id:
                    from ecommerce.product.models import Products as ProductModel
                    product_obj = ProductModel.objects.filter(id=product_id).first()
                    if product_obj:
                        item_data['product'] = product_obj.id
            item_data['purchase'] = purchase.id
            
            # Check if the item already exists or create a new one
            # Determine how to find the purchase item: by stock_item or product
            if stock_item:
                purchase_item = PurchaseItems.objects.filter(purchase=purchase, stock_item=stock_item).first()
            elif product_obj:
                purchase_item = PurchaseItems.objects.filter(purchase=purchase, product=product_obj).first()
            else:
                purchase_item = None
            
            from .serializers import PurchaseItemWriteSerializer
            if purchase_item:
                item_serializer = PurchaseItemWriteSerializer(purchase_item, data=item_data, partial=partial)
            else:
                item_serializer = PurchaseItemWriteSerializer(data=item_data)

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
                return Response({'error': 'Purchase order must be fully approved'}, status=status.HTTP_400_BAD_REQUEST)

            # Create purchase from order
            purchase_data = {
                'supplier': order.supplier.id if order.supplier else None,
                'purchase_order': order.id,
                'purchase_status': 'ordered',
                'payment_status': 'pending',
                'grand_total': order.approved_budget or 0,
                'sub_total': order.approved_budget or 0,
                'purchase_id': generate_ref_no('PO')
            }

            serializer = self.get_serializer(data=purchase_data)
            serializer.is_valid(raise_exception=True)
            # inherit branch from order if available
            if order.branch:
                purchase = serializer.save(added_by=request.user, branch=order.branch)
            else:
                purchase = serializer.save(added_by=request.user)

            # Convert order requisition items into purchase items
            for req_item in order.requisition.items.all():
                # Inventory items reference StockInventory
                if req_item.item_type == 'inventory' and req_item.stock_item:
                    PurchaseItems.objects.create(
                        purchase=purchase,
                        stock_item=req_item.stock_item,
                        qty=req_item.quantity,
                        unit_price=req_item.stock_item.buying_price or 0,
                        sub_total=(req_item.stock_item.buying_price or 0) * (req_item.quantity or 1)
                    )
                else:
                    # For services/external items, create a line with no stock_item
                    unit_price = req_item.estimated_price or 0
                    PurchaseItems.objects.create(
                        purchase=purchase,
                        stock_item=None,
                        product=None,
                        qty=req_item.quantity or 1,
                        unit_price=unit_price,
                        sub_total=unit_price * (req_item.quantity or 1)
                    )

            # Update order status
            order.status = 'processed'
            order.save()

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except PurchaseOrder.DoesNotExist:
            return Response({'error': 'Purchase order not found'}, status=status.HTTP_404_NOT_FOUND)

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
