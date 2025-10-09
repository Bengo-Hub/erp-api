"""
Compatibility shim for integrations services imports.

Provides CommunicationAnalyticsService by delegating to
communications_services to match existing imports in views.
"""
from .communication_services import CommunicationAnalyticsService  # re-export

__all__ = [
    "CommunicationAnalyticsService",
]

"""
Enhanced Communication Services for Task 3.1
Provides comprehensive communication management including:
- Enhanced notification preferences
- Communication analytics
- Bounce handling
- Spam prevention
- Communication testing
"""
import logging
import re
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.db.models import Sum
from celery import shared_task

from ..models import (
    UserNotificationPreferences, CommunicationAnalytics, BounceRecord,
    SpamPreventionRule, CommunicationTest, EmailLog, SMSLog
)
from ..notifications.services import NotificationService
from ..notifications.email import EmailService
from ..notifications.sms import SMSService

logger = logging.getLogger('integrations')
User = get_user_model()


class CommunicationAnalyticsService:
    """Service for tracking and analyzing communication performance"""
    
    def __init__(self):
        self.cache_timeout = 3600  # 1 hour
    
    def track_email_sent(self, email_log: EmailLog, template_name: str = None, campaign_name: str = None):
        """Track email sent for analytics"""
        try:
            analytics, created = CommunicationAnalytics.objects.get_or_create(
                analytics_type='email',
                date=email_log.sent_at.date(),
                template_name=template_name,
                defaults={
                    'campaign_name': campaign_name,
                    'total_sent': 0,
                    'delivered': 0,
                    'failed': 0,
                    'bounced': 0,
                    'opened': 0,
                    'clicked': 0,
                    'unsubscribed': 0,
                }
            )
            
            analytics.total_sent += 1
            
            # Update status-based counts
            if email_log.status == 'SENT':
                analytics.delivered += 1
            elif email_log.status == 'FAILED':
                analytics.failed += 1
            
            analytics.calculate_rates()
            analytics.save()
            
            # Clear cache
            cache_key = f"comm_analytics_email_{analytics.date}"
            cache.delete(cache_key)
            
        except Exception as e:
            logger.error(f"Error tracking email sent: {str(e)}")
    
    def track_email_opened(self, email_log: EmailLog):
        """Track email opened for analytics"""
        try:
            analytics = CommunicationAnalytics.objects.filter(
                analytics_type='email',
                date=email_log.sent_at.date(),
                template_name=email_log.template.name if email_log.template else None
            ).first()
            
            if analytics:
                analytics.opened += 1
                analytics.calculate_rates()
                analytics.save()
                
                # Clear cache
                cache_key = f"comm_analytics_email_{analytics.date}"
                cache.delete(cache_key)
                
        except Exception as e:
            logger.error(f"Error tracking email opened: {str(e)}")
    
    def track_email_clicked(self, email_log: EmailLog):
        """Track email clicked for analytics"""
        try:
            analytics = CommunicationAnalytics.objects.filter(
                analytics_type='email',
                date=email_log.sent_at.date(),
                template_name=email_log.template.name if email_log.template else None
            ).first()
            
            if analytics:
                analytics.clicked += 1
                analytics.calculate_rates()
                analytics.save()
                
                # Clear cache
                cache_key = f"comm_analytics_email_{analytics.date}"
                cache.delete(cache_key)
                
        except Exception as e:
            logger.error(f"Error tracking email clicked: {str(e)}")
    
    def track_sms_sent(self, sms_log: SMSLog, template_name: str = None, campaign_name: str = None):
        """Track SMS sent for analytics"""
        try:
            analytics, created = CommunicationAnalytics.objects.get_or_create(
                analytics_type='sms',
                date=sms_log.sent_at.date(),
                template_name=template_name,
                defaults={
                    'campaign_name': campaign_name,
                    'total_sent': 0,
                    'delivered': 0,
                    'failed': 0,
                    'bounced': 0,
                }
            )
            
            analytics.total_sent += 1
            
            # Update status-based counts
            if sms_log.status == 'SENT':
                analytics.delivered += 1
            elif sms_log.status == 'FAILED':
                analytics.failed += 1
            
            analytics.calculate_rates()
            analytics.save()
            
            # Clear cache
            cache_key = f"comm_analytics_sms_{analytics.date}"
            cache.delete(cache_key)
            
        except Exception as e:
            logger.error(f"Error tracking SMS sent: {str(e)}")
    
    def get_analytics_summary(self, start_date: datetime, end_date: datetime, 
                            analytics_type: str = None, template_name: str = None) -> Dict[str, Any]:
        """Get analytics summary for a date range"""
        try:
            cache_key = f"comm_analytics_summary_{start_date.date()}_{end_date.date()}_{analytics_type}_{template_name}"
            cached_result = cache.get(cache_key)
            
            if cached_result:
                return cached_result
            
            queryset = CommunicationAnalytics.objects.filter(
                date__range=[start_date.date(), end_date.date()]
            )
            
            if analytics_type:
                queryset = queryset.filter(analytics_type=analytics_type)
            
            if template_name:
                queryset = queryset.filter(template_name=template_name)
            
            # Aggregate data
            summary = queryset.aggregate(
                total_sent=Sum('total_sent'),
                total_delivered=Sum('delivered'),
                total_failed=Sum('failed'),
                total_bounced=Sum('bounced'),
                total_opened=Sum('opened'),
                total_clicked=Sum('clicked'),
                total_unsubscribed=Sum('unsubscribed'),
                total_cost=Sum('total_cost'),
            )
            
            # Calculate rates
            total_sent = summary['total_sent'] or 0
            total_delivered = summary['total_delivered'] or 0
            
            if total_sent > 0:
                delivery_rate = (total_delivered / total_sent) * 100
                open_rate = (summary['total_opened'] or 0) / total_delivered * 100 if total_delivered > 0 else 0
                click_rate = (summary['total_clicked'] or 0) / total_delivered * 100 if total_delivered > 0 else 0
            else:
                delivery_rate = open_rate = click_rate = 0
            
            result = {
                'total_sent': total_sent,
                'total_delivered': total_delivered,
                'total_failed': summary['total_failed'] or 0,
                'total_bounced': summary['total_bounced'] or 0,
                'total_opened': summary['total_opened'] or 0,
                'total_clicked': summary['total_clicked'] or 0,
                'total_unsubscribed': summary['total_unsubscribed'] or 0,
                'delivery_rate': round(delivery_rate, 2),
                'open_rate': round(open_rate, 2),
                'click_rate': round(click_rate, 2),
                'total_cost': summary['total_cost'] or 0,
            }
            
            # Cache the result
            cache.set(cache_key, result, self.cache_timeout)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting analytics summary: {str(e)}")
            return {}
