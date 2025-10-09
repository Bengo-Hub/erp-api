from django.contrib import admin
from .models import Campaign, CampaignPerformance


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'campaign_type', 'status', 'priority', 'is_active',
        'start_date', 'end_date', 'impressions', 'clicks', 'conversions'
    ]
    list_filter = [
        'campaign_type', 'status', 'priority', 'is_active', 'is_default',
        'created_at'
    ]
    search_fields = ['name', 'title', 'description']
    readonly_fields = [
        'impressions', 'clicks', 'conversions', 'revenue_generated',
        'created_at', 'updated_at'
    ]
    filter_horizontal = ['target_audience', 'target_branches', 'featured_products']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'campaign_type', 'status', 'priority')
        }),
        ('Content', {
            'fields': ('title', 'description', 'image', 'badge')
        }),
        ('Targeting', {
            'fields': ('target_audience', 'target_branches', 'featured_products')
        }),
        ('Timing', {
            'fields': ('start_date', 'end_date', 'is_active', 'is_default')
        }),
        ('Settings', {
            'fields': ('budget', 'max_impressions', 'max_clicks', 'landing_page_url', 'cta_text')
        }),
        ('Metrics', {
            'fields': ('impressions', 'clicks', 'conversions', 'revenue_generated'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(CampaignPerformance)
class CampaignPerformanceAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'date', 'impressions', 'clicks', 'conversions', 'revenue']
    list_filter = ['date', 'campaign__campaign_type']
    search_fields = ['campaign__name']
    date_hierarchy = 'date'
    readonly_fields = ['campaign']
