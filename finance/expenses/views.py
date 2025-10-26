from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .models import Expense, ExpenseCategory, ExpensePayment, PaymentAccounts
from .serializers import ExpenseSerializer, ExpenseCategorySerializer, PaymentSerializer, PaymentAccountSerializer
from .functions import generate_enxpense_ref
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class ExpenseCategoryViewSet(BaseModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated]


class PaymentAccountViewSet(BaseModelViewSet):
    queryset = PaymentAccounts.objects.all()
    serializer_class = PaymentAccountSerializer
    permission_classes = [IsAuthenticated]


class ExpenseViewSet(BaseModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Optimize queries with select_related for foreign keys."""
        queryset = super().get_queryset()
        return queryset.select_related('category', 'business', 'branch')

    def create(self, request, *args, **kwargs):
        """Create expense with auto-generated reference number."""
        try:
            correlation_id = self.get_correlation_id()
            
            # Auto-generate reference number
            request.data['reference_no'] = generate_enxpense_ref("EP")
            
            serializer = self.get_serializer(data=request.data)
            
            if not serializer.is_valid():
                return APIResponse.validation_error(
                    message='Validation failed',
                    errors=serializer.errors,
                    correlation_id=correlation_id
                )
            
            instance = serializer.save()
            
            # Log creation
            self.log_operation(
                operation=AuditTrail.CREATE,
                obj=instance,
                reason=f'Created expense {instance.reference_no}'
            )
            
            return APIResponse.created(
                data=self.get_serializer(instance).data,
                message='Expense created successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error creating expense: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            return APIResponse.server_error(
                message='Error creating expense',
                error_id=str(e),
                correlation_id=correlation_id
            )


class PaymentViewSet(BaseModelViewSet):
    queryset = ExpensePayment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Optimize queries with select_related for foreign keys."""
        queryset = super().get_queryset()
        return queryset.select_related('expense', 'payment_account')
