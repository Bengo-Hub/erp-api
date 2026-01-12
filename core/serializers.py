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



# ApplicationBrandingSettingsSerializer removed - use business.serializers.BussinessSerializer
# or business.serializers.BrandingSettingsSerializer for branding settings
# Branding is now managed at the business level for multi-tenant support

# Legacy alias for backward compatibility
BanksSerializer = BankInstitutionSerializer

class BankBranchesSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankBranches
        fields = '__all__'

# BannerSerializer moved to centralized campaigns app
# Use: from crm.campaigns.serializers import CampaignSerializer
    


