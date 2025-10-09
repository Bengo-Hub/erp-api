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

class AccountTypesViewSet(viewsets.ModelViewSet):
    queryset = AccountTypes.objects.all()
    serializer_class = AccountTypesSerializer
    permission_classes = [IsAuthenticated]

class PaymentAccountsViewSet(viewsets.ModelViewSet):
    queryset = PaymentAccounts.objects.all()
    serializer_class = PaymentAccountsSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'account_number']
    filterset_fields = ['account_type']
    
    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        """Get all transactions for a specific account"""
        account = self.get_object()
        transactions = Transaction.objects.filter(account=account).order_by('-transaction_date')
        page = self.paginate_queryset(transactions)
        if page is not None:
            serializer = TransactionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
            
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        """Calculate the current balance for an account"""
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
        
        return Response({
            'account_id': account.id,
            'account_name': account.name,
            'opening_balance': account.opening_balance,
            'credits': credits,
            'debits': debits,
            'current_balance': balance
        })

class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all().order_by('-transaction_date')
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
        
        return Response({
            'start_date': start_date,
            'end_date': end_date,
            'income_total': income_total,
            'expense_total': expense_total,
            'payment_total': payment_total,
            'refund_total': refund_total,
            'net_total': income_total + refund_total - expense_total - payment_total
        })

class VoucherViewSet(viewsets.ModelViewSet):
    queryset = Voucher.objects.all().order_by('-voucher_date')
    serializer_class = VoucherSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['reference_number', 'remarks']
    filterset_fields = ['status', 'voucher_type']
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update the status of a voucher"""
        voucher = self.get_object()
        status = request.data.get('status')
        remarks = request.data.get('remarks', '')
        
        if status not in [s[0] for s in Voucher.VOUCHER_STATUS_CHOICES]:
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Update voucher status
        voucher.status = status
        voucher.save()
        
        # Create audit record
        from .models import VoucherAudit
        VoucherAudit.objects.create(
            voucher=voucher,
            action=status,
            action_by=request.user,
            remarks=remarks
        )
        
        # If status is 'Paid', create a transaction record
        if status == 'Paid':
            # Logic to create a payment transaction would go here
            pass
        
        return Response({'status': 'success', 'voucher': VoucherSerializer(voucher).data})
    
    @action(detail=True, methods=['post'])
    def add_item(self, request, pk=None):
        """Add an item to a voucher"""
        voucher = self.get_object()
        serializer = VoucherItemSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save(voucher=voucher)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)