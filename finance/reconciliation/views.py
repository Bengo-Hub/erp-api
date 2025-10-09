from datetime import datetime
from django.db import models
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import BankStatementLine
from .serializers import BankStatementLineSerializer
from finance.accounts.models import Transaction
from finance.payment.models import Payment


class BankStatementLineViewSet(viewsets.ModelViewSet):
    queryset = BankStatementLine.objects.all()
    serializer_class = BankStatementLineSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['description', 'external_ref']
    ordering_fields = ['statement_date', 'amount', 'created_at']
    throttle_scope = 'user'

    @action(detail=False, methods=['get'], url_path='unreconciled')
    def unreconciled(self, request):
        qs = self.get_queryset().filter(is_reconciled=False)
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='match')
    def match(self, request, pk=None):
        line = self.get_object()
        transaction_id = request.data.get('transaction_id')
        payment_id = request.data.get('payment_id')

        if not transaction_id and not payment_id:
            return Response({'detail': 'Provide transaction_id or payment_id to match.'}, status=status.HTTP_400_BAD_REQUEST)

        if transaction_id:
            try:
                txn = Transaction.objects.get(pk=transaction_id)
            except Transaction.DoesNotExist:
                return Response({'detail': 'Transaction not found.'}, status=status.HTTP_404_NOT_FOUND)
            line.matched_transaction = txn

        if payment_id:
            try:
                pay = Payment.objects.get(pk=payment_id)
            except Payment.DoesNotExist:
                return Response({'detail': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)
            line.matched_payment = pay

        line.is_reconciled = True
        line.save(update_fields=['matched_transaction', 'matched_payment', 'is_reconciled'])
        return Response(self.get_serializer(line).data)


