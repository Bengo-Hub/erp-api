"""
Integration API views for the decomposed ERP.

Only generic, ERP-retained integration concerns remain here:
- Exchange-rate API settings + manual FX fetch (feeds core.ExchangeRate)
- A lightweight integration health/summary endpoint

Payment gateways (Mpesa/Paystack/PayPal/Card), KRA/eTIMS fiscalisation, bank &
government service integrations, and webhook delivery all moved to treasury-api.
Notification providers moved to notifications-api.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.utils import timezone
from datetime import timedelta

from .models import ExchangeRateAPISettings
from .serializers import ExchangeRateAPISettingsSerializer
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def integration_health_check(request):
    """Generic health summary for the ERP's retained integrations (outbox + FX)."""
    from .models import EventOutbox
    pending = EventOutbox.objects.filter(status=EventOutbox.STATUS_PENDING).count()
    failed = EventOutbox.objects.filter(status=EventOutbox.STATUS_FAILED).count()
    fx = ExchangeRateAPISettings.objects.filter(is_active=True).first()
    return Response({
        'status': 'ok',
        'outbox': {'pending': pending, 'failed': failed},
        'exchange_rate': {
            'configured': bool(fx),
            'last_fetch_at': fx.last_fetch_at.isoformat() if fx and fx.last_fetch_at else None,
            'last_fetch_status': fx.last_fetch_status if fx else None,
        },
    })


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
