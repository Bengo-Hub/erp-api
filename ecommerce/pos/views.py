import decimal
from ecommerce.product.models import *
from django.db.models import Sum, Q, Window, F, Count
from django.db.models.functions import RowNumber
import sys
from datetime import date,timedelta
from .models import *
from rest_framework.response import Response
from rest_framework import status
from ecommerce.pos.models import *
from business.models import Bussiness,Branch
from finance.expenses.models import Expense
from crm.contacts.models import Contact,ContactAccount
from rest_framework import viewsets,pagination
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework import permissions
from rest_framework.views import APIView
from .serializers import *
from ecommerce.stockinventory.models import StockInventory
from finance.accounts.models import TransactionPayment
# Legacy Mpesa transactions are centralized; remove direct dependency
from datetime import date
from rest_framework.pagination import LimitOffsetPagination
from django.db import transaction
#import aiohttp
from django.shortcuts import get_object_or_404
from .functions import generate_sale_id,generate_return_id
from .utils import calculate_profit
from django.contrib.auth import get_user_model
from django.utils import timezone
from finance.payment.models import POSPayment, PaymentMethod
from finance.payment.serializers import CreatePOSPaymentSerializer
from rest_framework import viewsets, permissions, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
import logging

from .models import (
    Sales, salesItems, Register, CustomerReward, 
    SuspendedSale, POSAdvanceSaleRecord
)
from .serializers import (
    SalesSerializer, SalesItemsSerializer, RegisterSerializer,
    CustomerRewardSerializer, SuspendedSaleSerializer,
    POSAdvanceSaleRecordSerializer, CreateStaffAdvanceSaleSerializer,
    StaffAdvanceBalanceSerializer
)
from ecommerce.stockinventory.models import StockInventory
from crm.contacts.models import Contact
from hrm.employees.models import Employee
from finance.payment.services import PaymentOrchestrationService
from finance.accounts.models import TransactionPayment
from .models import MpesaTransaction

logger = logging.getLogger(__name__)

User=get_user_model()

class CustomPagination(pagination.PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class TransactionViewSet(viewsets.ModelViewSet):
    queryset = MpesaTransaction.objects.all()
    serializer_class = TransactionSerializer
    pagination_class = CustomPagination

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()

    def list(self, request, *args, **kwargs):
        queryset=super().get_queryset()
        # Get transactions by type (deposit/withdrawal)
        transaction_type = request.query_params.get('type', None)
        if transaction_type:
           queryset = queryset.filter(transactionType=transaction_type)
        # Get transactions by date
        fromdate = request.query_params.get('fromdate', None)
        todate = request.query_params.get('todate', None)
        if fromdate and todate:
           queryset = queryset.filter(date__range=[fromdate,todate])
        # Perform analytics for general deposit and withdrawal totals
        total_deposit =queryset.filter(transactionType='deposit').aggregate(total=Sum('amount'))['total']
        total_withdrawal = queryset.filter(transactionType='withdrawal').aggregate(total=Sum('amount'))['total']
        # Get the daily summary for deposits and withdrawals separately
        daily_summary_deposit = queryset.filter(date=date.today(), transactionType='deposit').aggregate(total=Sum('amount'))['total']
        daily_summary_withdrawal = queryset.filter(date=date.today(), transactionType='withdrawal').aggregate(total=Sum('amount'))['total']
        serializer = TransactionSerializer(queryset, many=True)

        return Response({
            'total_deposit': total_deposit or 0,
            'total_withdrawal': total_withdrawal or 0,
            'daily_summary': {
                "deposits":daily_summary_deposit or 0,
                "withdrawals":daily_summary_withdrawal or 0,
                },
            'transactions':serializer.data,
        })

class CustomerRewardViewSet(viewsets.ModelViewSet):
    queryset = CustomerReward.objects.all()
    serializer_class = CustomerRewardSerializer

class SalesReturnViewSet(viewsets.ViewSet):
    queryset=SalesReturn.objects.all()
    pagination_class = CustomPagination

    def create(self, request):
        resp = {'icon':'info','title': 'Request info', 'msg': 'Default response!'}
        try:
            with transaction.atomic():
                sale_id = request.data.get('sale_id')
                returned_item_skus = [request.data.get('sku')] if isinstance(request.data.get('sku'), str) else request.data.get('sku', [])
                qtys = [request.data.get('qty')] if isinstance(request.data.get('qty'), str) else request.data.get('qty', [])
                return_amount = float(request.data.get('return_total',0))
                attendant_id = request.data.get('attendant')
                # Get or create the original sale instance
                original_sale = get_object_or_404(Sales, sale_id=sale_id)
                # Check if attendant exists
                attendant = None
                if attendant_id:
                    attendant = get_object_or_404(User, pk=attendant_id)
                # Create sales return instance
                sales_return = SalesReturn.objects.create(
                    return_id=generate_return_id(),
                    original_sale=original_sale,
                    attendant=attendant,
                    reason=request.data.get('return_reason', None),
                    return_amount=return_amount,
                    return_amount_due=return_amount,
                    payment_status='pending' if return_amount > 0 else 'paid'
                )
                for i, sku in enumerate(returned_item_skus):
                    stockitem = StockInventory.objects.filter(Q(product__sku=sku)|Q(variation__sku=sku)).first()
                    qty=int(qtys[i])
                    stockitem.stock_level+=qty
                    stockitem.save()
                    # Create returned items
                    ReturnedItem.objects.create(
                        return_record=sales_return,
                        stock_item=stockitem,
                        qty=qty
                    )
            resp = {'icon':'success','title': 'Success', 'msg': 'Sale Return record saved successfully!'}
            return Response(resp, status=status.HTTP_201_CREATED)
        except Exception as e:
            resp = {'icon':'error','title': 'Error', 'msg': str(e)}
        return Response(resp, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def list(self,request):
        offset = int(request.data.get('offset', 0))
        limit = int(request.data.get('limit', 10))
        status = request.data.get('status', None)
        fromdate = request.data.get('fromdate', None)
        todate = request.data.get('todate', None)
        branch_id = request.data.get('branch_id', None)
        queryset=self.queryset.values("id","date_returned","return_id","original_sale__sale_id","original_sale__customer__id","original_sale__customer__user__first_name","original_sale__customer__user__last_name","original_sale__salesitems__stock_item__branch__id","original_sale__salesitems__stock_item__branch__business__name","reason","return_amount","return_amount_due","payment_status").order_by('-return_id').distinct()
        user = request.user
        filter_branches=Branch.objects.filter(id=branch_id).first()
        if filter_branches:
            queryset=queryset.filter(original_sale__salesitems__stock_item__branch__in=filter_branches)            
        if not request.user.is_superuser:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=user)
            employee_branches = Branch.objects.filter(business__employees__user=user)
            # Combine the two sets of branches using OR operator
            branches =  owned_branches | employee_branches
            queryset=queryset.filter(original_sale__salesitems__stock_item__branch__in=branches)   
        if status:
            queryset = queryset.filter(payment_status=status)
        # Get transactions by date
        if fromdate and todate:
            queryset = queryset.filter(date_returned__range=[fromdate,todate])
        count=len(queryset)
        # Apply offset and limit to the queryset
        queryset = queryset[offset: offset + limit]
        returns_data=[]
        returns=queryset
        for item in returns:
            data = {}
            return_items=[]
            data['id']=item['id']
            data['date']=item['date_returned']
            data['invoice_no']=item['return_id']
            data['parent_sale']=item['original_sale__sale_id']
            data['customer']={"id":item['original_sale__customer__id'],"name":f"{item['original_sale__customer__user__first_name']} {item['original_sale__customer__user__last_name']}"}
            data['location']={"id":item['original_sale__salesitems__stock_item__branch__id'],"name":item['original_sale__salesitems__stock_item__branch__business__name']}
            data['reason']=item['reason']
            data['return_amount']=item['return_amount']
            data['return_amount_due']=item['return_amount_due']
            data['payment_status']=item['payment_status']
            for return_item in ReturnedItem.objects.filter(return_record__id=item['id']).values('id','qty','stock_item__product__title','stock_item__product__sku','stock_item__variation__title','stock_item__variation__sku'):
                return_items.append({
                    "quantity":return_item['qty'],
                    "product":{"title":return_item['stock_item__product__title'],"sku":return_item['stock_item__product__sku']},
                    "variation":{"title":return_item['stock_item__variation__title'],"sku":return_item['stock_item__variation__sku']},
                })
            data['return_items']=return_items
            data['total_items']=len(return_items)
            data['count']=count
            returns_data.append(data)
        return Response(returns_data)
    
class SalesReturnRefundViewSet(viewsets.ViewSet):
    queryset=SalesReturn.objects.all()
    pagination_class = CustomPagination

    def create(self, request):
        resp = {'icon':'info','title': 'Request info', 'msg': 'Default response!'}
        try:
            print(request.data)
            return_id = request.data.get('invoice_no',None)
            refund_amount= decimal.Decimal(request.data.get('refund_total', 0))
            print(type(refund_amount),refund_amount)
            refund_method = request.data.get('refund_method')
            paynote = request.data.get('pay_note','')
            payfile = request.data.get('pay_document',None)
            attendant_id = request.data.get('attendant_id',None)
            paid_by=User.objects.get(id=attendant_id)
            sale_return=SalesReturn.objects.get(return_id=return_id)
            paid_to=sale_return.original_sale.customer
            contact=Contact.objects.get(user=paid_to.user)
            print(paid_to)
            with transaction.atomic():
                # Get the sale instance 
                sale_return.return_amount_due-=refund_amount
                sale_return.payment_status='Paid' if sale_return.return_amount_due == 0 else 'due'
                sale_return.save()
                # Perform refund based on refund method
                if refund_method == 'cash':
                    # Refund cash
                    # Perform cash refund logic here
                    pass
                elif refund_method == 'debit':
                    # Debit customer's account
                    customer = paid_to
                    customer_account,created = ContactAccount.objects.get_or_create(contact=contact)
                    customer_account.account_balance -= refund_amount
                    customer_account.save()
                elif refund_method == 'credit':
                    # Credit customer's account
                    customer = paid_to
                    customer_account,created= ContactAccount.objects.get_or_create(contact=contact)
                    customer_account.account_balance += refund_amount
                    customer_account.save()
                elif refund_method == 'pay_cash_to_customer_account':
                    # Pay cash to customer's account
                    customer = paid_to
                    customer_account,created= ContactAccount.objects.get_or_create(contact=contact)
                    customer_account.advance_balance += refund_amount
                    customer_account.save()
                # add returns payment
                tr,_=TransactionPayment.objects.get_or_create(
                    transaction_type ='Sale',
                    ref_no = return_id,
                    amount_paid=refund_amount,
                    payment_method =refund_method,
                    payment_account = None,
                    payment_document=payfile,
                    payment_note = paynote,
                    paid_by = paid_by,
                    paid_to =paid_to.user,
                    payment_date =timezone.now()
                )
                resp = {'icon':'success','title': 'Success', 'msg': 'Payment for sales return updated successfully!'}
                return Response(resp,status=status.HTTP_201_CREATED)
        except Exception as e:
            resp = {'icon':'error','title': 'Error', 'msg': str(e)}
            return Response(resp,status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SuspendedSaleViewSet(viewsets.ModelViewSet):
    queryset = SuspendedSale.objects.all()
    serializer_class = SuspendedSaleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(created_by=self.request.user)
        return queryset

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        suspended_sale = self.get_object()
        
        # Create a new sale from the suspended sale
        sale_data = {
            'items': suspended_sale.items,
            'customer': suspended_sale.customer,
            'notes': f"Resumed from suspended sale {suspended_sale.reference_number}"
        }
        
        sale_serializer = SaleSerializer(data=sale_data)
        if sale_serializer.is_valid():
            sale = sale_serializer.save()
            suspended_sale.delete()  # Remove the suspended sale
            return Response(sale_serializer.data)
        return Response(sale_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class POSViewSet(viewsets.ModelViewSet):
    queryset = Sales.objects.all()
    serializer_class = SalesSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['post'])
    def create_sale(self, request):
        with transaction.atomic():
            # Create the sale first
            sale_serializer = self.get_serializer(data=request.data)
            if not sale_serializer.is_valid():
                return Response(sale_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            sale = sale_serializer.save()

            # Process payment
            payment_data = {
                'sale': sale.id,
                'amount': request.data.get('grand_total'),
                'payment_method': request.data.get('payment_method'),
                'tendered_amount': request.data.get('tendered_amount', 0),
                'notes': f"POS Sale {sale.reference_number}"
            }

            payment_serializer = CreatePOSPaymentSerializer(data=payment_data)
            if not payment_serializer.is_valid():
                return Response(payment_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            payment = payment_serializer.save()

            # Update sale with payment info
            sale.payment_status = 'paid'
            sale.save()

            return Response({
                'sale': SaleSerializer(sale).data,
                'payment': payment_serializer.data
            }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def void_sale(self, request, pk=None):
        sale = self.get_object()
        with transaction.atomic():
            # Void the sale
            sale.status = 'voided'
            sale.voided_by = request.user
            sale.voided_at = timezone.now()
            sale.save()

            # Refund the payment if it exists
            if hasattr(sale, 'payment'):
                payment = sale.payment
                payment.status = 'refunded'
                payment.save()

            return Response({'status': 'sale voided'})

    @action(detail=True, methods=['post'])
    def refund_sale(self, request, pk=None):
        sale = self.get_object()
        refund_amount = request.data.get('amount')
        reason = request.data.get('reason')

        with transaction.atomic():
            # Create refund record
            if hasattr(sale, 'payment'):
                payment = sale.payment
                refund = payment.refunds.create(
                    amount=refund_amount,
                    reason=reason,
                    processed_by=request.user
                )

                # Update sale status
                sale.payment_status = 'refunded'
                sale.save()

                return Response({'status': 'refund processed', 'refund_id': refund.id})
            return Response({'error': 'No payment found for this sale'}, 
                          status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def sales_list(self, request):
        """Get filtered list of sales with pagination and filtering"""
        try:
            queryset = self.get_queryset()
            
            # Apply filters
            status_filter = request.query_params.get('status', '')
            from_date = request.query_params.get('fromdate', '')
            to_date = request.query_params.get('todate', '')
            
            if status_filter:
                queryset = queryset.filter(status=status_filter)
            
            if from_date and to_date:
                queryset = queryset.filter(date_added__date__range=[from_date, to_date])
            elif from_date:
                queryset = queryset.filter(date_added__date__gte=from_date)
            elif to_date:
                queryset = queryset.filter(date_added__date__lte=to_date)
            
            # Apply pagination
            limit = int(request.query_params.get('limit', 25))
            offset = int(request.query_params.get('offset', 0))
            
            # Order by most recent first
            queryset = queryset.order_by('-date_added')
            
            # Apply pagination
            total_count = queryset.count()
            sales = queryset[offset:offset + limit]
            
            # Serialize the data
            serializer = self.get_serializer(sales, many=True)
            
            return Response({
                'count': total_count,
                'next': f"?limit={limit}&offset={offset + limit}" if offset + limit < total_count else None,
                'previous': f"?limit={limit}&offset={max(0, offset - limit)}" if offset > 0 else None,
                'results': serializer.data
            })
            
        except Exception as e:
            return Response({
                'error': 'Failed to fetch sales list',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def recent_sales(self, request):
        """Get recent sales for the POS dashboard"""
        try:
            queryset = self.get_queryset()
            
            # Get recent sales (last 10 by default)
            limit = int(request.query_params.get('limit', 10))
            
            # Order by most recent first and limit results
            recent_sales = queryset.order_by('-date_added')[:limit]
            
            # Serialize the data
            serializer = self.get_serializer(recent_sales, many=True)
            
            return Response({
                'sales': serializer.data,
                'count': len(recent_sales)
            })
            
        except Exception as e:
            return Response({
                'error': 'Failed to fetch recent sales',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def receipt_data(self, request):
        """Get receipt data for a specific sale"""
        try:
            sale_id = request.query_params.get('id')
            if not sale_id:
                return Response({
                    'error': 'Sale ID is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            sale = get_object_or_404(Sales, id=sale_id)
            serializer = self.get_serializer(sale)
            
            return Response(serializer.data)
            
        except Exception as e:
            return Response({
                'error': 'Failed to fetch receipt data',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def checkregister(self, request):
        """Check if a register is open for a user at a specific location"""
        try:
            user_id = request.query_params.get('user_id')
            branch_id = request.query_params.get('branch_id')
            
            if not user_id or not branch_id:
                return Response({
                    'error': 'User ID and Location ID are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if there's a register for this user and location
            register = Register.objects.filter(
                user_id=user_id,
                branch_id=branch_id    
            ).first()
            
            if not register:
                return Response({
                    'register_exists': False,
                    'needs_creation': True,
                    'message': 'No register found for this user and location'
                })
            
            if register.is_open:
                # Register is open, return current status
                return Response({
                    'register_exists': True,
                    'is_open': True,
                    'register_id': register.id,
                    'opened_at': register.opened_at,
                    'opened_by': register.opened_by.username if register.opened_by else None,
                    'cash_at_opening': register.cash_at_opening,
                    'current_balance': register.get_current_balance(),
                    'sales_count': register.get_sales_count(),
                    'total_sales_amount': register.get_total_sales_amount()
                })
            else:
                # Register exists but is closed
                return Response({
                    'register_exists': True,
                    'is_open': False,
                    'register_id': register.id,
                    'closed_at': register.closed_at,
                    'closed_by': register.closed_by.username if register.closed_by else None,
                    'cash_at_closing': register.cash_at_closing,
                    'message': 'Register exists but is currently closed'
                })
                
        except Exception as e:
            return Response({
                'error': 'Failed to check register status',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RegisterViewSet(viewsets.ModelViewSet):
    queryset = Register.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['post'])
    def create_or_get_register(self, request):
        """Create a new register or get existing one for a user and branch"""
        try:
            user_id = request.data.get('user_id')
            branch_id = request.data.get('branch_id')
            
            if not user_id or not branch_id:
                return Response({
                    'error': 'User ID and Branch ID are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if there's already a register for this user and branch
            existing_register = Register.objects.filter(
                user_id=user_id,
                branch_id=branch_id
            ).first()
            
            if existing_register:
                return Response({
                    'register_exists': True,
                    'register_id': existing_register.id,
                    'is_open': existing_register.is_open,
                    'message': 'Register already exists for this user and branch'
                })
            
            # Create a new register
            new_register = Register.objects.create(
                user_id=user_id,
                branch_id=branch_id,
                is_open=False
            )
            
            return Response({
                'register_exists': False,
                'register_id': new_register.id,
                'is_open': new_register.is_open,
                'message': 'New register created successfully'
            })
            
        except Exception as e:
            return Response({
                'error': 'Failed to create or get register',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def open_register(self, request, pk=None):
        """Open a register for a user"""
        try:
            register = self.get_object()
            opening_balance = request.data.get('opening_balance', 0)
            notes = request.data.get('notes', '')
            
            # Use the model method to open register
            register.open_register(
                user=request.user,
                opening_balance=opening_balance,
                notes=notes
            )
            
            return Response({
                'status': 'success',
                'message': 'Register opened successfully',
                'register_id': register.id,
                'opened_at': register.opened_at,
                'opening_balance': register.cash_at_opening
            })
            
        except ValueError as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'error': 'Failed to open register',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def close_register(self, request, pk=None):
        """Close a register for a user"""
        try:
            register = self.get_object()
            closing_balance = request.data.get('closing_balance', 0)
            notes = request.data.get('notes', '')
            
            # Use the model method to close register
            register.close_register(
                user=request.user,
                closing_balance=closing_balance,
                notes=notes
            )
            
            # Get sales summary
            sales_summary = self.get_sales_summary(register)
            
            return Response({
                'status': 'success',
                'message': 'Register closed successfully',
                'register_id': register.id,
                'closed_at': register.closed_at,
                'closing_balance': register.cash_at_closing,
                'summary': sales_summary
            })
            
        except ValueError as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'error': 'Failed to close register',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_sales_summary(self, register):
        # Get all sales since register was opened
        sales = Sales.objects.filter(
            date_added__gte=register.opened_at,
            date_added__lte=register.closed_at or timezone.now()
        )

        # Calculate totals by payment method
        payment_totals = {}
        for payment_method in PaymentMethod.objects.all():
            total = POSPayment.objects.filter(
                sale__in=sales,
                payment_method=payment_method,
                status='completed'
            ).aggregate(total=Sum('amount'))['total'] or 0
            payment_totals[payment_method.name] = total

        return {
            'total_sales': sum(payment_totals.values()),
            'payment_totals': payment_totals,
            'transaction_count': sales.count()
        }

    @action(detail=False, methods=['get'])
    def get_register_summary(self, request):
        """Get register summary with sales data"""
        try:
            user_id = request.query_params.get('user_id')
            branch_id = request.query_params.get('branch_id')
            
            if not user_id or not branch_id:
                return Response({
                    'error': 'User ID and Branch ID are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get register for the user and branch
            register = get_object_or_404(Register, user_id=user_id, branch_id=branch_id)
            
            # Get sales summary
            sales_summary = self.get_sales_summary(register)
            
            # Get additional register details
            register_details = {
                'id': register.id,
                'is_open': register.is_open,
                'opened_at': register.opened_at,
                'opened_by': None,  # Register model doesn't have opened_by field
                'opening_balance': register.cash_at_opening,
                'closing_balance': register.cash_at_closing,
                'branch': register.branch.name if register.branch else None
            }
            
            # Get sold products
            sold_products = Sales.objects.filter(
                date_added__gte=register.opened_at,
                date_added__lte=register.closed_at or timezone.now()
            ).values('items__product__name').annotate(
                total_quantity=Sum('items__quantity'),
                total_amount=Sum('grand_total')
            )
            
            # Get sales data by date
            sales_data = Sales.objects.filter(
                date_added__gte=register.opened_at,
                date_added__lte=register.closed_at or timezone.now()
            ).values('date_added__date').annotate(
                total_sales=Sum('grand_total'),
                count=Count('id')
            ).order_by('date_added__date')
            
            return Response({
                'registerDetails': register_details,
                'sold_products': list(sold_products),
                'sales_data': list(sales_data),
                'sold_products_by_brand': [],  # Placeholder for brand grouping
                'payment_methods': sales_summary['payment_totals']
            })
            
        except Exception as e:
            return Response({
                'error': 'Failed to fetch register summary',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Staff Advance Views
class StaffAdvanceSaleViewSet(viewsets.ModelViewSet):
    """
    API endpoint for staff advance sales.
    This allows staff to purchase items against their salary or loan repayments.
    """
    queryset = POSAdvanceSaleRecord.objects.all()
    serializer_class = POSAdvanceSaleRecordSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateStaffAdvanceSaleSerializer
        return POSAdvanceSaleRecordSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            pos_record = serializer.save()
            return Response({
                'status': 'success',
                'message': 'Staff advance sale created successfully',
                'reference_id': pos_record.reference_id,
                'id': pos_record.id
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], url_path='by-staff/(?P<staff_id>[^/.]+)')
    def by_staff(self, request, staff_id=None):
        """Get all advance sales for a specific staff member"""
        # Find all advance records linked to this employee through Advances model
        employee = get_object_or_404(Employee, id=staff_id)
        advances = POSAdvanceSaleRecord.objects.filter(advance__employee=employee)
        serializer = self.get_serializer(advances, many=True)
        return Response(serializer.data)

class StaffAdvanceBalanceViewSet(viewsets.ViewSet):
    """
    API endpoint for checking staff advance balance.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def retrieve(self, request, pk=None):
        employee = get_object_or_404(Employee, pk=pk)
        serializer = StaffAdvanceBalanceSerializer(employee)
        return Response(serializer.data)


# Payment-related Views
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_sale_details(request, id):
    """Get detailed information about a sale including all items and payment information"""
    try:
        sale = Sales.objects.select_related(
            'customer', 'attendant'
        ).prefetch_related(
            'salesitems__stock_item__product',
            'salesitems__stock_item__product__images',
            'salesitems__stock_item__variation'
        ).get(id=id)
        
        # Serialize the sale including all related data
        serializer = SalesDetailSerializer(sale, context={'request': request})
        return Response(serializer.data)
    except Sales.DoesNotExist:
        return Response(
            {'status': 'failed', 'msg': f'Sale with ID {id} not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error getting sale details: {str(e)}")
        return Response(
            {'status': 'failed', 'msg': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_sale_payments(request, id):
    """Get payment history for a specific sale from the finance module"""
    try:
        # Verify sale exists
        sale = Sales.objects.get(id=id)
        
        # Get payments from finance module
        payments = TransactionPayment.objects.filter(
            transaction_type='Sale',
            ref_no=sale.sale_id or str(sale.id)
        ).order_by('-payment_date')
        
        # Add M-Pesa transactions if any
        mpesa_payments = MpesaTransaction.objects.filter(
            entity_type='pos_sale',
            entity_id=str(sale.id)
        ).order_by('-created_at')
        
        # Combine all payment records
        payment_data = []
        
        # Add regular transaction payments
        for payment in payments:
            payment_data.append({
                'date': payment.payment_date,
                'payment_method': payment.payment_method,
                'amount': payment.amount_paid,
                'transaction_id': payment.transaction_id or '',
                'notes': payment.payment_note or '',
                'recorded_by': payment.paid_by.get_full_name() if payment.paid_by else ''
            })
        
        # Add M-Pesa payments
        for payment in mpesa_payments:
            payment_data.append({
                'date': payment.created_at,
                'payment_method': 'mpesa',
                'amount': payment.amount,
                'transaction_id': payment.mpesa_receipt,
                'notes': f'M-Pesa payment from {payment.phone_number}',
                'recorded_by': payment.created_by.get_full_name() if payment.created_by else 'System'
            })
        
        return Response(payment_data)
    except Sales.DoesNotExist:
        return Response(
            {'status': 'failed', 'msg': f'Sale with ID {id} not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error retrieving payment history: {str(e)}")
        return Response(
            {'status': 'failed', 'msg': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def process_pos_payment(request):
    """Process payment for POS sale using centralized payment system"""
    try:
        sale_id = request.data.get('sale_id')
        amount = request.data.get('amount')
        payment_method = request.data.get('payment_method')
        transaction_details = request.data.get('transaction_details', {})
        
        if not all([sale_id, amount, payment_method]):
            return Response({
                'status': 'failed',
                'message': 'Missing required parameters: sale_id, amount, payment_method'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get the sale
        sale = get_object_or_404(Sales, id=sale_id)
        
        # Use centralized payment service
        payment_service = PaymentOrchestrationService()
        success, message, payment = payment_service.process_pos_payment(
            sale=sale,
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
        logger.error(f"Error processing POS payment: {str(e)}")
        return Response({
            'status': 'failed',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
