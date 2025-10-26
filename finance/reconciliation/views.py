from datetime import datetime
from django.db import models
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import BankStatementLine
from .serializers import BankStatementLineSerializer
from finance.accounts.models import Transaction
from finance.payment.models import Payment
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class BankStatementLineViewSet(BaseModelViewSet):
    queryset = BankStatementLine.objects.all().select_related('matched_transaction', 'matched_payment')
    serializer_class = BankStatementLineSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['description', 'external_ref']
    ordering_fields = ['statement_date', 'amount', 'created_at']
    throttle_scope = 'user'

    @action(detail=False, methods=['get'], url_path='unreconciled')
    def unreconciled(self, request):
        """Get all unreconciled bank statement lines"""
        try:
            correlation_id = get_correlation_id(request)
            qs = self.get_queryset().filter(is_reconciled=False)
            serializer = self.get_serializer(qs, many=True)
            return APIResponse.success(data=serializer.data, message='Unreconciled statements retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching unreconciled statements: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving unreconciled statements', error_id=str(e), correlation_id=get_correlation_id(request))

    @action(detail=True, methods=['post'], url_path='match')
    def match(self, request, pk=None):
        """Match a bank statement line to a transaction or payment"""
        try:
            correlation_id = get_correlation_id(request)
            line = self.get_object()
            transaction_id = request.data.get('transaction_id')
            payment_id = request.data.get('payment_id')

            if not transaction_id and not payment_id:
                return APIResponse.bad_request(message='Provide transaction_id or payment_id to match', error_id='missing_match_id', correlation_id=correlation_id)

            old_matched_txn = line.matched_transaction
            old_matched_pay = line.matched_payment

            if transaction_id:
                try:
                    txn = Transaction.objects.get(pk=transaction_id)
                except Transaction.DoesNotExist:
                    return APIResponse.not_found(message='Transaction not found', correlation_id=correlation_id)
                line.matched_transaction = txn

            if payment_id:
                try:
                    pay = Payment.objects.get(pk=payment_id)
                except Payment.DoesNotExist:
                    return APIResponse.not_found(message='Payment not found', correlation_id=correlation_id)
                line.matched_payment = pay

            line.is_reconciled = True
            line.save(update_fields=['matched_transaction', 'matched_payment', 'is_reconciled', 'updated_at'])
            AuditTrail.log(operation=AuditTrail.UPDATE, module='finance', entity_type='BankStatementLine', entity_id=line.id, user=request.user, reason='Bank statement line matched', request=request)
            return APIResponse.success(data=self.get_serializer(line).data, message='Statement line matched successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error matching statement line: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error matching statement line', error_id=str(e), correlation_id=get_correlation_id(request))


