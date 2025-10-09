"""
Django admin configuration for notifications app
"""
from django.contrib import admin
from .models import (
    NotificationIntegration, EmailConfiguration, SMSConfiguration, PushConfiguration,
    EmailTemplate, SMSTemplate, PushTemplate, EmailLog, SMSLog, PushLog,
    InAppNotification, UserNotificationPreferences, NotificationAnalytics,
    BounceRecord, SpamPreventionRule, NotificationTest
)


@admin.register(NotificationIntegration)
class NotificationIntegrationAdmin(admin.ModelAdmin):
    list_display = ['name', 'integration_type', 'is_active', 'is_default']
    list_filter = ['integration_type', 'is_active', 'is_default']
    search_fields = ['name']


@admin.register(EmailConfiguration)
class EmailConfigurationAdmin(admin.ModelAdmin):
    list_display = ['integration', 'provider', 'from_email']
    list_filter = ['provider']
    search_fields = ['integration__name']


@admin.register(SMSConfiguration)
class SMSConfigurationAdmin(admin.ModelAdmin):
    list_display = ['integration', 'provider']
    list_filter = ['provider']
    search_fields = ['integration__name']


@admin.register(PushConfiguration)
class PushConfigurationAdmin(admin.ModelAdmin):
    list_display = ['integration', 'provider']
    list_filter = ['provider']
    search_fields = ['integration__name']


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'subject', 'category', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name']


@admin.register(SMSTemplate)
class SMSTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name']


@admin.register(PushTemplate)
class PushTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'title', 'category', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name']


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ['subject', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['subject']


@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    list_display = ['status', 'created_at']
    list_filter = ['status', 'created_at']


@admin.register(PushLog)
class PushLogAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['title']


@admin.register(InAppNotification)
class InAppNotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'title', 'notification_type', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['user__username', 'title']


@admin.register(UserNotificationPreferences)
class UserNotificationPreferencesAdmin(admin.ModelAdmin):
    list_display = ['user', 'email_notifications_enabled', 'sms_notifications_enabled']
    list_filter = ['email_notifications_enabled', 'sms_notifications_enabled']
    search_fields = ['user__username']


@admin.register(NotificationAnalytics)
class NotificationAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_sent']
    list_filter = ['date']
    search_fields = ['date']


@admin.register(BounceRecord)
class BounceRecordAdmin(admin.ModelAdmin):
    list_display = ['bounce_type', 'created_at']
    list_filter = ['bounce_type', 'created_at']


@admin.register(SpamPreventionRule)
class SpamPreventionRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'rule_type', 'is_active']
    list_filter = ['rule_type', 'is_active']
    search_fields = ['name']


@admin.register(NotificationTest)
class NotificationTestAdmin(admin.ModelAdmin):
    list_display = ['test_type', 'created_at']
    list_filter = ['test_type', 'created_at']