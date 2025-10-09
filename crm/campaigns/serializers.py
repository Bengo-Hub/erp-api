from rest_framework import serializers
from .models import Campaign, CampaignPerformance


class CampaignPerformanceSerializer(serializers.ModelSerializer):
    """Serializer for CampaignPerformance model"""
    
    class Meta:
        model = CampaignPerformance
        fields = [
            'id', 'campaign', 'date', 'impressions', 'clicks', 
            'conversions', 'revenue'
        ]


class CampaignSerializer(serializers.ModelSerializer):
    """Serializer for Campaign model"""
    
    # Computed fields
    is_running = serializers.ReadOnlyField()
    ctr = serializers.ReadOnlyField()
    conversion_rate = serializers.ReadOnlyField()
    roi = serializers.ReadOnlyField()
    
    # Related fields
    daily_performance = CampaignPerformanceSerializer(many=True, read_only=True)
    
    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'campaign_type', 'status', 'priority',
            'title', 'description', 'image', 'badge',
            'target_audience', 'target_branches', 'featured_products',
            'seller', 'stock_items', 'branch',
            'start_date', 'end_date', 'is_active', 'is_default',
            'impressions', 'clicks', 'conversions', 'revenue_generated',
            'budget', 'max_impressions', 'max_clicks',
            'landing_page_url', 'cta_text',
            'created_by', 'created_at', 'updated_at',
            'is_running', 'ctr', 'conversion_rate', 'roi',
            'daily_performance'
        ]
        read_only_fields = [
            'impressions', 'clicks', 'conversions', 'revenue_generated',
            'created_at', 'updated_at'
        ]


class CampaignListSerializer(serializers.ModelSerializer):
    """Simplified serializer for campaign lists"""
    
    is_running = serializers.ReadOnlyField()
    ctr = serializers.ReadOnlyField()
    conversion_rate = serializers.ReadOnlyField()
    
    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'campaign_type', 'status', 'priority',
            'title', 'description', 'image', 'badge', 
            'start_date', 'end_date', 'is_active', 'is_default',
            'impressions', 'clicks', 'conversions', 'revenue_generated',
            'is_running', 'ctr', 'conversion_rate', 'created_at'
        ]


class CampaignCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating campaigns"""
    
    class Meta:
        model = Campaign
        fields = [
            'name', 'campaign_type', 'status', 'priority',
            'title', 'description', 'image', 'badge',
            'target_audience', 'target_branches', 'featured_products',
            'seller', 'stock_items', 'branch',
            'start_date', 'end_date', 'is_active', 'is_default',
            'budget', 'max_impressions', 'max_clicks',
            'landing_page_url', 'cta_text'
        ]


class CampaignUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating campaigns"""
    
    class Meta:
        model = Campaign
        fields = [
            'name', 'campaign_type', 'status', 'priority',
            'title', 'description', 'image', 'badge',
            'target_audience', 'target_branches', 'featured_products',
            'seller', 'stock_items', 'branch',
            'start_date', 'end_date', 'is_active', 'is_default',
            'budget', 'max_impressions', 'max_clicks',
            'landing_page_url', 'cta_text'
        ]
        extra_kwargs = {
            'name': {'required': False},
            'campaign_type': {'required': False},
            'start_date': {'required': False},
            'end_date': {'required': False}
        }
