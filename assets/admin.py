from django.contrib import admin
from .models import AssetCategory, Asset, AssetTransfer, AssetMaintenance, AssetDisposal

@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'description')
    ordering = ('name',)

@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ('asset_tag', 'name', 'category', 'status', 'location', 'assigned_to', 'current_value')
    list_filter = ('status', 'category', 'branch', 'is_active', 'created_at')
    search_fields = ('asset_tag', 'name', 'serial_number', 'model')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('asset_tag', 'name', 'description', 'category')
        }),
        ('Identification', {
            'fields': ('serial_number', 'model', 'manufacturer')
        }),
        ('Financial Information', {
            'fields': ('purchase_date', 'purchase_cost', 'current_value', 'depreciation_rate')
        }),
        ('Location & Assignment', {
            'fields': ('location', 'branch', 'assigned_to', 'custodian')
        }),
        ('Status & Condition', {
            'fields': ('status', 'condition', 'is_active')
        }),
        ('Maintenance', {
            'fields': ('warranty_expiry', 'last_maintenance', 'next_maintenance')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_by'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    ordering = ('-created_at',)

@admin.register(AssetTransfer)
class AssetTransferAdmin(admin.ModelAdmin):
    list_display = ('asset', 'from_location', 'to_location', 'transfer_date', 'transferred_by')
    list_filter = ('transfer_date', 'transferred_by')
    search_fields = ('asset__asset_tag', 'asset__name', 'from_location', 'to_location')
    readonly_fields = ('transfer_date',)
    ordering = ('-transfer_date',)

@admin.register(AssetMaintenance)
class AssetMaintenanceAdmin(admin.ModelAdmin):
    list_display = ('asset', 'maintenance_type', 'scheduled_date', 'status', 'performed_by', 'cost')
    list_filter = ('maintenance_type', 'status', 'scheduled_date')
    search_fields = ('asset__asset_tag', 'asset__name', 'performed_by')
    readonly_fields = ('scheduled_date',)
    ordering = ('-scheduled_date',)

@admin.register(AssetDisposal)
class AssetDisposalAdmin(admin.ModelAdmin):
    list_display = ('asset', 'disposal_date', 'disposal_method', 'disposal_value', 'approved_by')
    list_filter = ('disposal_method', 'disposal_date')
    search_fields = ('asset__asset_tag', 'asset__name', 'reason')
    readonly_fields = ('disposal_date',)
    ordering = ('-disposal_date',)
