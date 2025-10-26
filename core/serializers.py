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
    class Meta:
        model = BrandingSettings
        fields = ['id', 'app_name', 'tagline', 'footer_text', 'primary_color', 'secondary_color',
                  'text_color', 'background_color', 'logo_url', 'logo', 'favicon_url', 
                  'watermark_url', 'watermark', 'enable_dark_mode', 'theme_preset', 'menu_mode',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

# Legacy alias for backward compatibility
BanksSerializer = BankInstitutionSerializer

class BankBranchesSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankBranches
        fields = '__all__'

# BannerSerializer moved to centralized campaigns app
# Use: from crm.campaigns.serializers import CampaignSerializer
    


