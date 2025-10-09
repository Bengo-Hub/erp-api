from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from .models import Expense, ExpenseCategory, ExpensePayment, PaymentAccounts
from .serializers import ExpenseSerializer, ExpenseCategorySerializer, PaymentSerializer, PaymentAccountSerializer
from .functions import generate_enxpense_ref

class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer

class PaymentAccountViewSet(viewsets.ModelViewSet):
    queryset = PaymentAccounts.objects.all()
    serializer_class = PaymentAccountSerializer

class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer

    def create(self, request, *args, **kwargs):
        request.data['reference_no'] = generate_enxpense_ref("EP")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

class PaymentViewSet(viewsets.ModelViewSet):
    queryset = ExpensePayment.objects.all()
    serializer_class = PaymentSerializer
