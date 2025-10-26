"""
Integration Health Check Views

Provides endpoints to test connectivity and configuration status of all integrations.
Useful for system monitoring and troubleshooting.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status as http_status
from django.utils import timezone
import logging

from .services.config_service import IntegrationConfigService
from .models import Integrations, MpesaSettings, KRASettings, BankAPISettings, GovernmentServiceSettings
from notifications.models import SMSConfiguration, EmailConfiguration

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def integration_health_check(request):
    """
    Get health status of all integrations.
    Tests connectivity and configuration for each integration type.
    
    Returns:
    - configured: Whether settings exist in DB
    - active: Whether integration is marked active
    - connection: Tuple (success, message) from connectivity test
    """
    try:
        health_status = IntegrationConfigService.get_all_integration_status()
        
        return Response({
            'success': True,
            'integrations': health_status,
            'generated_at': timezone.now().isoformat(),
        }, status=http_status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting integration health: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mpesa_health_check(request):
    """
    Test M-Pesa API connectivity.
    Attempts to get access token to verify credentials.
    """
    try:
        success, message = IntegrationConfigService.test_mpesa_connection()
        
        return Response({
            'success': success,
            'message': message,
            'configured': IntegrationConfigService.is_integration_configured('MPESA'),
            'active': IntegrationConfigService.is_integration_active('MPESA'),
            'tested_at': timezone.now().isoformat(),
        }, status=http_status.HTTP_200_OK if success else http_status.HTTP_503_SERVICE_UNAVAILABLE)
        
    except Exception as e:
        logger.error(f"Error testing M-Pesa connection: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def kra_health_check(request):
    """
    Test KRA eTIMS API connectivity.
    Attempts to get access token to verify credentials.
    """
    try:
        success, message = IntegrationConfigService.test_kra_connection()
        
        return Response({
            'success': success,
            'message': message,
            'configured': IntegrationConfigService.is_kra_configured(),
            'tested_at': timezone.now().isoformat(),
        }, status=http_status.HTTP_200_OK if success else http_status.HTTP_503_SERVICE_UNAVAILABLE)
        
    except Exception as e:
        logger.error(f"Error testing KRA connection: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sms_health_check(request):
    """
    Test SMS provider connectivity.
    """
    try:
        success, message = IntegrationConfigService.test_sms_connection()
        
        return Response({
            'success': success,
            'message': message,
            'configured': IntegrationConfigService.is_sms_configured(),
            'tested_at': timezone.now().isoformat(),
        }, status=http_status.HTTP_200_OK if success else http_status.HTTP_503_SERVICE_UNAVAILABLE)
        
    except Exception as e:
        logger.error(f"Error testing SMS connection: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_health_check(request):
    """
    Test Email provider connectivity.
    """
    try:
        success, message = IntegrationConfigService.test_email_connection()
        
        return Response({
            'success': success,
            'message': message,
            'configured': IntegrationConfigService.is_email_configured(),
            'tested_at': timezone.now().isoformat(),
        }, status=http_status.HTTP_200_OK if success else http_status.HTTP_503_SERVICE_UNAVAILABLE)
        
    except Exception as e:
        logger.error(f"Error testing Email connection: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def clear_integration_cache(request):
    """
    Clear all integration configuration caches.
    Admin only - use after updating integration settings.
    """
    try:
        IntegrationConfigService.clear_config_cache()
        
        return Response({
            'success': True,
            'message': 'Integration configuration cache cleared',
            'cleared_at': timezone.now().isoformat(),
        }, status=http_status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error clearing integration cache: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def integration_summary(request):
    """
    Get summary of all configured integrations.
    Shows which integrations are configured and active.
    """
    try:
        # Payment integrations
        payment_integrations = Integrations.objects.filter(integration_type='PAYMENT').values(
            'id', 'name', 'is_active', 'is_default', 'created_at'
        )
        
        # Notification integrations
        from notifications.models import NotificationIntegration
        notification_integrations = NotificationIntegration.objects.all().values(
            'id', 'name', 'integration_type', 'provider', 'is_active', 'is_default'
        )
        
        # Count settings
        settings_count = {
            'mpesa': MpesaSettings.objects.count(),
            'kra': KRASettings.objects.count(),
            'bank_api': BankAPISettings.objects.count(),
            'govt_services': GovernmentServiceSettings.objects.count(),
            'sms': SMSConfiguration.objects.count(),
            'email': EmailConfiguration.objects.count(),
        }
        
        return Response({
            'success': True,
            'data': {
                'payment_integrations': list(payment_integrations),
                'notification_integrations': list(notification_integrations),
                'settings_configured': settings_count,
            },
            'generated_at': timezone.now().isoformat(),
        }, status=http_status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting integration summary: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

