from django.contrib import admin
from .models import TaxCategory, Tax, TaxGroup, TaxGroupItem


class TaxInline(admin.TabularInline):
    """Inline for Tax entries within TaxCategory admin."""
    model = Tax
    extra = 1
    fields = ('name', 'rate', 'calculation_type', 'is_active', 'is_default')


@admin.register(TaxCategory)
class TaxCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'business', 'is_active', 'created_at')
    list_filter = ('is_active', 'business', 'created_at')
    search_fields = ('name',)
    inlines = [TaxInline]


@admin.register(Tax)
class TaxAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'rate', 'calculation_type', 'is_active', 'is_default', 'created_at')
    list_filter = ('is_active', 'category', 'is_vat', 'is_withholding', 'created_at')
    search_fields = ('name', 'category__name')


@admin.register(TaxGroup)
class TaxGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'business', 'is_active', 'created_at')
    list_filter = ('is_active', 'business', 'created_at')
    search_fields = ('name',)


@admin.register(TaxGroupItem)
class TaxGroupItemAdmin(admin.ModelAdmin):
    list_display = ('tax_group', 'tax', 'order')
    list_filter = ('tax_group', 'tax')
    search_fields = ('tax_group__name', 'tax__name')
