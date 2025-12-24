from rest_framework import serializers
from .models import *
# EmailConfigsSerializer moved to centralized notifications app
# Use: from notifications.serializers import EmailConfigurationSerializer


class RegionsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Regions
        fields = '__all__'

class DepartmentsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Departments
        fields = '__all__'

class ProjectsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Projects
        fields = '__all__'

class ProjectCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectCategory
        fields = '__all__'

class BankInstitutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankInstitution
        fields = '__all__'


class RegionalSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegionalSettings
        fields = ['id', 'timezone', 'date_format', 'financial_year_end', 'currency', 
                  'currency_symbol', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class BrandingSettingsSerializer(serializers.ModelSerializer):
    logo_full_url = serializers.SerializerMethodField()
    watermark_full_url = serializers.SerializerMethodField()
    
    class Meta:
        model = BrandingSettings
        fields = ['id', 'app_name', 'tagline', 'footer_text', 'primary_color', 'secondary_color',
                  'text_color', 'background_color', 'logo_url', 'logo', 'logo_full_url', 'favicon_url', 
                  'watermark_url', 'watermark', 'watermark_full_url', 'enable_dark_mode', 'theme_preset', 'menu_mode',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_logo_full_url(self, obj):
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
            return obj.logo.url
        return None
    
    def get_watermark_full_url(self, obj):
        if obj.watermark:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.watermark.url)
            return obj.watermark.url
        return None

# Legacy alias for backward compatibility
BanksSerializer = BankInstitutionSerializer

class BankBranchesSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankBranches
        fields = '__all__'

# BannerSerializer moved to centralized campaigns app
# Use: from crm.campaigns.serializers import CampaignSerializer
    


