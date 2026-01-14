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
    KRASettings, WebhookEndpoint, WebhookEvent, MpesaSettings, ExchangeRateAPISettings,
    PaystackSettings
)
from .serializers import (
    KRASettingsSerializer, WebhookEndpointSerializer, WebhookEventSerializer,
    MpesaSettingsSerializer, ExchangeRateAPISettingsSerializer, PaystackSettingsSerializer
)
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)

class KRASettingsViewSet(BaseModelViewSet):
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


class MpesaSettingsViewSet(viewsets.ModelViewSet):
    """ViewSet to manage M-Pesa settings with RBAC protection."""
    serializer_class = MpesaSettingsSerializer
    permission_classes = [IsAuthenticated]
    queryset = MpesaSettings.objects.all()

    def get_permissions(self):
        # Only admins can create/update/delete settings. Authenticated users can read.
        if self.action in ['list', 'retrieve', 'current']:
            return [IsAuthenticated()]
        return [IsAdminUser()]

    @action(detail=False, methods=['get'])
    def current(self, request):
        obj = MpesaSettings.objects.order_by('-updated_at').first() if hasattr(MpesaSettings, 'updated_at') else MpesaSettings.objects.first()
        if not obj:
            # Provide safe defaults from config service
            from .services.config_service import IntegrationConfigService
            return Response(IntegrationConfigService.DEFAULT_MPESA_CONFIG)
        return Response(self.get_serializer(obj).data)


class PaystackSettingsViewSet(viewsets.ModelViewSet):
    """
    ViewSet to manage Paystack payment gateway settings.
    Provides endpoints to configure API credentials and test connectivity.
    """
    serializer_class = PaystackSettingsSerializer
    permission_classes = [IsAuthenticated]
    queryset = PaystackSettings.objects.all()

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'current', 'status']:
            return [IsAuthenticated()]
        return [IsAdminUser()]

    @action(detail=False, methods=['get'])
    def current(self, request):
        """Get the currently configured Paystack settings."""
        obj = PaystackSettings.objects.order_by('-updated_at').first()
        if not obj:
            return Response({
                'is_test_mode': True,
                'base_url': 'https://api.paystack.co',
                'default_currency': 'KES',
                'enabled_channels': ['card', 'bank_transfer', 'mobile_money'],
                'is_configured': False,
            })
        data = self.get_serializer(obj).data
        data['is_configured'] = True
        return Response(data)

    @action(detail=False, methods=['get'])
    def status(self, request):
        """Check Paystack connection status and fetch totals."""
        try:
            from integrations.payments.paystack_payment import PaystackPaymentService
            result = PaystackPaymentService.get_transaction_totals()

            if result.get('success'):
                return Response({
                    'is_configured': True,
                    'is_connected': True,
                    'total_transactions': result.get('total_transactions', 0),
                    'total_volume': float(result.get('total_volume', 0)),
                    'pending_transfers': float(result.get('pending_transfers', 0)),
                })
            else:
                return Response({
                    'is_configured': True,
                    'is_connected': False,
                    'error': result.get('error', 'Connection failed'),
                })
        except Exception as exc:
            logger.error(f"Error checking Paystack status: {exc}")
            return Response({
                'is_configured': False,
                'is_connected': False,
                'error': str(exc)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def test_connection(self, request):
        """Test Paystack API connection with current credentials."""
        try:
            from integrations.payments.paystack_payment import PaystackPaymentService
            result = PaystackPaymentService.get_transaction_totals()

            if result.get('success'):
                return Response({
                    'success': True,
                    'message': 'Paystack connection successful',
                    'total_transactions': result.get('total_transactions', 0),
                })
            else:
                return Response({
                    'success': False,
                    'message': 'Connection failed',
                    'error': result.get('error'),
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.error(f"Error testing Paystack connection: {exc}")
            return Response({
                'success': False,
                'error': str(exc)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def banks(self, request):
        """Get list of supported banks for bank transfers."""
        try:
            from integrations.payments.paystack_payment import PaystackPaymentService
            country = request.query_params.get('country', 'kenya')
            result = PaystackPaymentService.list_banks(country)

            if result.get('success'):
                return Response({
                    'success': True,
                    'banks': result.get('banks', []),
                })
            else:
                return Response({
                    'success': False,
                    'error': result.get('error'),
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.error(f"Error fetching Paystack banks: {exc}")
            return Response({
                'success': False,
                'error': str(exc)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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


class ExchangeRateAPISettingsViewSet(viewsets.ModelViewSet):
    """
    ViewSet to manage Exchange Rate API settings.
    Provides endpoints to configure API credentials, trigger manual fetches,
    and view fetch status.
    """
    serializer_class = ExchangeRateAPISettingsSerializer
    permission_classes = [IsAuthenticated]
    queryset = ExchangeRateAPISettings.objects.all()

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'current', 'status']:
            return [IsAuthenticated()]
        return [IsAdminUser()]

    @action(detail=False, methods=['get'])
    def current(self, request):
        """Get the currently active exchange rate API settings."""
        obj = ExchangeRateAPISettings.objects.filter(is_active=True).first()
        if not obj:
            return Response({
                'provider': 'EXCHANGERATE_HOST',
                'provider_name': 'exchangerate.host',
                'api_endpoint': 'https://api.exchangerate.host/live',
                'source_currency': 'USD',
                'target_currencies': ['KES', 'USD', 'EUR', 'GBP'],
                'is_active': False,
                'last_fetch_status': 'pending',
            })
        return Response(self.get_serializer(obj).data)

    @action(detail=False, methods=['get'])
    def status(self, request):
        """Get the current fetch status and last update time."""
        obj = ExchangeRateAPISettings.objects.filter(is_active=True).first()
        if not obj:
            return Response({
                'is_configured': False,
                'last_fetch_at': None,
                'last_fetch_status': None,
                'next_fetch': None,
            })

        # Calculate next fetch time
        next_fetch = None
        if obj.fetch_time:
            now = timezone.now()
            next_fetch_date = now.replace(
                hour=obj.fetch_time.hour,
                minute=obj.fetch_time.minute,
                second=0,
                microsecond=0
            )
            if next_fetch_date <= now:
                next_fetch_date += timedelta(days=1)
            next_fetch = next_fetch_date.isoformat()

        return Response({
            'is_configured': True,
            'provider': obj.provider_name,
            'last_fetch_at': obj.last_fetch_at.isoformat() if obj.last_fetch_at else None,
            'last_fetch_status': obj.last_fetch_status,
            'last_fetch_error': obj.last_fetch_error,
            'next_fetch': next_fetch,
            'target_currencies': obj.target_currencies,
        })

    @action(detail=False, methods=['post'])
    def fetch_now(self, request):
        """Manually trigger exchange rate fetch (bypasses daily check)."""
        try:
            from integrations.tasks import manual_fetch_exchange_rates
            result = manual_fetch_exchange_rates.delay()
            return Response({
                'success': True,
                'message': 'Exchange rate fetch task queued',
                'task_id': str(result.id),
            })
        except Exception as exc:
            logger.error(f"Error triggering exchange rate fetch: {exc}")
            return Response({
                'success': False,
                'error': str(exc)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def latest_rates(self, request):
        """Get the latest exchange rates from local database."""
        try:
            from core.models import ExchangeRate
            today = timezone.now().date()

            # Get rates for today or the most recent date
            rates = ExchangeRate.objects.filter(
                source='api'
            ).order_by('-effective_date', 'from_currency', 'to_currency')

            # Get unique currency pairs with latest rates
            rate_dict = {}
            for rate in rates[:50]:  # Limit to 50 most recent
                key = f"{rate.from_currency}_{rate.to_currency}"
                if key not in rate_dict:
                    rate_dict[key] = {
                        'from_currency': rate.from_currency,
                        'to_currency': rate.to_currency,
                        'rate': float(rate.rate),
                        'effective_date': rate.effective_date.isoformat(),
                        'source': rate.source,
                    }

            return Response({
                'success': True,
                'rates': list(rate_dict.values()),
                'count': len(rate_dict),
            })
        except Exception as exc:
            logger.error(f"Error fetching latest rates: {exc}")
            return Response({
                'success': False,
                'error': str(exc)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)