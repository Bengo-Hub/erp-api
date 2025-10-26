from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from datetime import datetime, timedelta
from django.db.models import Sum, Q

from .models import AccountTypes, PaymentAccounts, Transaction, Voucher, VoucherItem
from .serializers import AccountTypesSerializer, PaymentAccountsSerializer, TransactionSerializer, VoucherSerializer, VoucherItemSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class AccountTypesViewSet(BaseModelViewSet):
    queryset = AccountTypes.objects.all()
    serializer_class = AccountTypesSerializer
    permission_classes = [IsAuthenticated]


class PaymentAccountsViewSet(BaseModelViewSet):
    queryset = PaymentAccounts.objects.all()
    serializer_class = PaymentAccountsSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'account_number']
    filterset_fields = ['account_type']
    
    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        """Get all transactions for a specific account"""
        try:
            correlation_id = get_correlation_id(request)
            account = self.get_object()
            
            transactions = Transaction.objects.filter(account=account).select_related('account').order_by('-transaction_date')
            
            page = self.paginate_queryset(transactions)
            if page is not None:
                serializer = TransactionSerializer(page, many=True)
                return self.get_paginated_response(serializer.data)
                
            serializer = TransactionSerializer(transactions, many=True)
            return APIResponse.success(
                data=serializer.data,
                message='Account transactions retrieved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error fetching transactions: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error retrieving transactions',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )
    
    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        """Calculate the current balance for an account"""
        try:
            correlation_id = get_correlation_id(request)
            account = self.get_object()
            
            # Get all credit transactions (income, refunds)
            credits = Transaction.objects.filter(
                account=account,
                transaction_type__in=['income', 'refund']
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            # Get all debit transactions (expenses, payments, transfers)
            debits = Transaction.objects.filter(
                account=account,
                transaction_type__in=['expense', 'payment', 'transfer']
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            # Calculate balance
            balance = account.opening_balance + credits - debits
            
            return APIResponse.success(
                data={
                    'account_id': account.id,
                    'account_name': account.name,
                    'opening_balance': account.opening_balance,
                    'credits': credits,
                    'debits': debits,
                    'current_balance': balance
                },
                message='Account balance calculated successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error calculating balance: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error calculating account balance',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )


class TransactionViewSet(BaseModelViewSet):
    queryset = Transaction.objects.all().select_related('account', 'created_by').order_by('-transaction_date')
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['description', 'reference_id']
    filterset_fields = ['account', 'transaction_type', 'reference_type']
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary of transactions by type"""
        try:
            correlation_id = get_correlation_id(request)
            today = datetime.now().date()
            start_date = request.query_params.get('start_date', (today - timedelta(days=30)).isoformat())
            end_date = request.query_params.get('end_date', today.isoformat())
            
            # Filter by date range
            transactions = Transaction.objects.filter(
                transaction_date__gte=start_date,
                transaction_date__lte=end_date
            )
            
            # Group by transaction type
            income_total = transactions.filter(transaction_type='income').aggregate(total=Sum('amount'))['total'] or 0
            expense_total = transactions.filter(transaction_type='expense').aggregate(total=Sum('amount'))['total'] or 0
            payment_total = transactions.filter(transaction_type='payment').aggregate(total=Sum('amount'))['total'] or 0
            refund_total = transactions.filter(transaction_type='refund').aggregate(total=Sum('amount'))['total'] or 0
            
            return APIResponse.success(
                data={
                    'start_date': start_date,
                    'end_date': end_date,
                    'income_total': income_total,
                    'expense_total': expense_total,
                    'payment_total': payment_total,
                    'refund_total': refund_total,
                    'net_total': income_total + refund_total - expense_total - payment_total
                },
                message='Transaction summary retrieved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error fetching transaction summary: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error retrieving transaction summary',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )


class VoucherViewSet(BaseModelViewSet):
    queryset = Voucher.objects.all().select_related('created_by').order_by('-voucher_date')
    serializer_class = VoucherSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['reference_number', 'remarks']
    filterset_fields = ['status', 'voucher_type']
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update the status of a voucher"""
        try:
            correlation_id = get_correlation_id(request)
            voucher = self.get_object()
            status = request.data.get('status')
            remarks = request.data.get('remarks', '')
            
            if status not in [s[0] for s in Voucher.VOUCHER_STATUS_CHOICES]:
                return APIResponse.bad_request(
                    message='Invalid status',
                    error_id='invalid_status',
                    correlation_id=correlation_id
                )
            
            # Update voucher status
            voucher.status = status
            voucher.save()
            
            # Create audit record
            AuditTrail.create(
                model_name='Voucher',
                model_id=voucher.id,
                action=status,
                action_by=request.user,
                remarks=remarks
            )
            
            # If status is 'Paid', create a transaction record
            if status == 'Paid':
                # Logic to create a payment transaction would go here
                pass
            
            return APIResponse.success(
                data=VoucherSerializer(voucher).data,
                message='Voucher status updated successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error updating voucher status: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error updating voucher status',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )
    
    @action(detail=True, methods=['post'])
    def add_item(self, request, pk=None):
        """Add an item to a voucher"""
        try:
            correlation_id = get_correlation_id(request)
            voucher = self.get_object()
            serializer = VoucherItemSerializer(data=request.data)
            
            if serializer.is_valid():
                serializer.save(voucher=voucher)
                return APIResponse.created(
                    data=serializer.data,
                    message='Voucher item added successfully',
                    correlation_id=correlation_id
                )
            return APIResponse.bad_request(
                data=serializer.errors,
                message='Invalid voucher item data',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error adding voucher item: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error adding voucher item',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )