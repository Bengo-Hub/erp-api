from django.shortcuts import render
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Contract, ContractOrderLink
from .serializers import ContractSerializer, ContractOrderLinkSerializer


# Create your views here.

class ContractViewSet(viewsets.ModelViewSet):
    queryset = Contract.objects.all()
    serializer_class = ContractSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'supplier__user__first_name', 'supplier__user__last_name']
    ordering_fields = ['start_date', 'end_date', 'value', 'created_at']

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        contract = self.get_object()
        contract.status = 'active'
        contract.save(update_fields=['status'])
        return Response(self.get_serializer(contract).data)

    @action(detail=True, methods=['post'], url_path='terminate')
    def terminate(self, request, pk=None):
        contract = self.get_object()
        contract.status = 'terminated'
        contract.save(update_fields=['status'])
        return Response(self.get_serializer(contract).data)


class ContractOrderLinkViewSet(viewsets.ModelViewSet):
    queryset = ContractOrderLink.objects.all()
    serializer_class = ContractOrderLinkSerializer
    permission_classes = [permissions.IsAuthenticated]
