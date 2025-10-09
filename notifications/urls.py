"""
URLs for the notifications app
"""
from django.urls import path, include
from . import views

app_name = 'notifications'

urlpatterns = [
    # API endpoints for notifications
    path('api/', include([
        # Email endpoints
        path('email/', include([
            path('send/', views.SendEmailView.as_view(), name='send_email'),
            path('templates/', views.EmailTemplateListView.as_view(), name='email_templates'),
        ])),
        
        # SMS endpoints
        path('sms/', include([
            path('send/', views.SendSMSView.as_view(), name='send_sms'),
            path('templates/', views.SMSTemplateListView.as_view(), name='sms_templates'),
        ])),
        
        # Push notification endpoints
        path('push/', include([
            path('send/', views.SendPushView.as_view(), name='send_push'),
            path('templates/', views.PushTemplateListView.as_view(), name='push_templates'),
        ])),
        
        # General notification endpoints
        path('send/', views.SendNotificationView.as_view(), name='send_notification'),
        path('bulk/', views.BulkNotificationView.as_view(), name='bulk_notification'),
        path('test/', views.TestNotificationView.as_view(), name='test_notification'),
        
        # In-app notification endpoints
        path('in-app/', include([
            path('', views.InAppNotificationListView.as_view(), name='in_app_list'),
            path('<int:notification_id>/read/', views.MarkNotificationReadView.as_view(), name='mark_read'),
            path('mark-all-read/', views.MarkAllNotificationsReadView.as_view(), name='mark_all_read'),
        ])),
    ])),
    
    # Webhook endpoints for external services
    path('webhooks/', include([
        path('email/bounce/', views.EmailBounceWebhookView.as_view(), name='email_bounce_webhook'),
        path('email/complaint/', views.EmailComplaintWebhookView.as_view(), name='email_complaint_webhook'),
        path('sms/delivery/', views.SMSDeliveryWebhookView.as_view(), name='sms_delivery_webhook'),
    ])),
]
