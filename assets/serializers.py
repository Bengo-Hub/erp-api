from rest_framework import serializers
from .models import (
    AssetCategory, Asset, AssetDepreciation,
    AssetInsurance, AssetAudit, AssetReservation, AssetTransfer,
    AssetMaintenance, AssetDisposal
)

class AssetCategorySerializer(serializers.ModelSerializer):
    subcategories_count = serializers.SerializerMethodField()

    class Meta:
        model = AssetCategory
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def get_subcategories_count(self, obj):
        return obj.subcategories.count()

class AssetSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True)
    custodian_name = serializers.CharField(source='custodian.get_full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    # Calculated fields
    depreciation_schedule = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'accumulated_depreciation', 'book_value')

    def get_depreciation_schedule(self, obj):
        years = self.context.get('years', 5)
        return obj.get_depreciation_schedule(years)

class AssetDepreciationSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)

    class Meta:
        model = AssetDepreciation
        fields = '__all__'
        read_only_fields = ('created_at',)

class AssetInsuranceSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)

    class Meta:
        model = AssetInsurance
        fields = '__all__'
        read_only_fields = ('created_at',)

class AssetAuditSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)
    auditor_name = serializers.CharField(source='auditor.get_full_name', read_only=True)
    custodian_verified_name = serializers.CharField(source='custodian_verified.get_full_name', read_only=True)

    class Meta:
        model = AssetAudit
        fields = '__all__'
        read_only_fields = ('created_at',)

class AssetReservationSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)
    reserved_by_name = serializers.CharField(source='reserved_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)

    class Meta:
        model = AssetReservation
        fields = '__all__'
        read_only_fields = ('created_at',)

class AssetTransferSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)
    from_user_name = serializers.CharField(source='from_user.get_full_name', read_only=True)
    to_user_name = serializers.CharField(source='to_user.get_full_name', read_only=True)
    transferred_by_name = serializers.CharField(source='transferred_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)

    class Meta:
        model = AssetTransfer
        fields = '__all__'
        read_only_fields = ('transfer_date',)

class AssetMaintenanceSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)

    class Meta:
        model = AssetMaintenance
        fields = '__all__'
        read_only_fields = ('scheduled_date',)

class AssetDisposalSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)

    class Meta:
        model = AssetDisposal
        fields = '__all__'
        read_only_fields = ('disposal_date',)
