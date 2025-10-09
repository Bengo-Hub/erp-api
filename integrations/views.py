"""
API Views for Enhanced Communication Features (Task 3.1)
Provides endpoints for:
- Notification preferences management
- Communication analytics
- Bounce handling
- Spam prevention
- Communication testing
"""
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.utils import timezone
from datetime import datetime, timedelta
from typing import Dict, Any

from .models import (
    KRASettings, WebhookEndpoint, WebhookEvent
)
from .serializers import (
    KRASettingsSerializer, WebhookEndpointSerializer, WebhookEventSerializer
)

class KRASettingsViewSet(viewsets.ModelViewSet):
    """ViewSet to manage KRA eTIMS settings with RBAC protection."""
    serializer_class = KRASettingsSerializer
    permission_classes = [IsAuthenticated]
    queryset = KRASettings.objects.all()

    def get_permissions(self):
        # Only admins can create/update/delete settings. Authenticated users can read.
        if self.action in ['list', 'retrieve', 'current']:
            return [IsAuthenticated()]
        return [IsAdminUser()]

    def perform_create(self, serializer):
        instance = serializer.save()
        return instance

    @action(detail=False, methods=['get'])
    def current(self, request):
        obj = KRASettings.objects.order_by('-updated_at').first()
        if not obj:
            return Response({
                'mode': 'sandbox',
                'base_url': 'https://api.sandbox.kra.go.ke',
                'token_path': '/oauth/token',
                'invoice_path': '/etims/v1/invoices',
                'invoice_status_path': '/etims/v1/invoices/status',
            })
        return Response(self.get_serializer(obj).data)

    @action(detail=False, methods=['post'])
    def validate_pin(self, request):
        """Validate a KRA PIN via KRAService."""
        try:
            pin = request.data.get('pin') or request.data.get('kra_pin')
            if not pin:
                return Response({'detail': 'pin is required'}, status=status.HTTP_400_BAD_REQUEST)
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.validate_pin(pin)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WebhookEndpointViewSet(viewsets.ModelViewSet):
    serializer_class = WebhookEndpointSerializer
    permission_classes = [IsAuthenticated]
    queryset = WebhookEndpoint.objects.all()


class WebhookEventViewSet(viewsets.ModelViewSet):
    serializer_class = WebhookEventSerializer
    permission_classes = [IsAuthenticated]
    queryset = WebhookEvent.objects.select_related('endpoint').all()

    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        try:
            from integrations.services import WebhookDeliveryService  # type: ignore
            event = self.get_object()
            job_id = WebhookDeliveryService.schedule_delivery(event.pk)
            return Response({'success': True, 'message': 'Delivery scheduled', 'job_id': job_id})
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def certificate(self, request):
        """Retrieve a KRA tax certificate for a given type and period."""
        try:
            tax_type = request.data.get('type') or request.data.get('tax_type')
            period = request.data.get('period')
            if not tax_type or not period:
                return Response({'detail': 'type and period are required'}, status=status.HTTP_400_BAD_REQUEST)
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.get_tax_certificate(tax_type, period)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def compliance(self, request):
        """Check KRA compliance for a PIN."""
        try:
            pin = request.data.get('pin') or request.data.get('kra_pin')
            if not pin:
                return Response({'detail': 'pin is required'}, status=status.HTTP_400_BAD_REQUEST)
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.check_compliance(pin)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def sync(self, request):
        """Sync tax data within a date range."""
        try:
            start_date = request.data.get('start_date')
            end_date = request.data.get('end_date')
            if not start_date or not end_date:
                return Response({'detail': 'start_date and end_date are required'}, status=status.HTTP_400_BAD_REQUEST)
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.sync_tax_data(start_date, end_date)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)