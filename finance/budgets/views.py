from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Budget, BudgetLine
from .serializers import BudgetSerializer, BudgetLineSerializer


class BudgetViewSet(viewsets.ModelViewSet):
    queryset = Budget.objects.all()
    serializer_class = BudgetSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['start_date', 'end_date', 'created_at']
    throttle_scope = 'user'

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        budget = self.get_object()
        budget.status = 'approved'
        budget.save(update_fields=['status'])
        return Response(self.get_serializer(budget).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        budget = self.get_object()
        budget.status = 'rejected'
        budget.save(update_fields=['status'])
        return Response(self.get_serializer(budget).data)


class BudgetLineViewSet(viewsets.ModelViewSet):
    queryset = BudgetLine.objects.all()
    serializer_class = BudgetLineSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'category']
    ordering_fields = ['amount']
    throttle_scope = 'user'
