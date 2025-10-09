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

# Legacy alias for backward compatibility
BanksSerializer = BankInstitutionSerializer

class BankBranchesSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankBranches
        fields = '__all__'

# BannerSerializer moved to centralized campaigns app
# Use: from crm.campaigns.serializers import CampaignSerializer
    


