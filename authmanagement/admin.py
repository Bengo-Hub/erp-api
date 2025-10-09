from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import Group
from django import forms
from .models import (
    CustomUser, PasswordPolicy,
    Backup, BackupConfig, BackupSchedule, UserLog, AccountRequest
)

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'phone', 'is_active', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'is_superuser')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'middle_name', 'phone', 'pic')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )

@admin.register(PasswordPolicy)
class PasswordPolicyAdmin(admin.ModelAdmin):
    list_display = ('id', 'min_length', 'require_uppercase', 'require_lowercase', 
                   'require_numbers', 'require_special_chars', 'password_expiry_days',
                   'max_login_attempts', 'lockout_duration_minutes', 'updated_at')
    list_editable = ('min_length', 'require_uppercase', 'require_lowercase',
                    'require_numbers', 'require_special_chars', 'password_expiry_days',
                    'max_login_attempts', 'lockout_duration_minutes')
    list_display_links = ('id',)
    list_filter = ('require_uppercase', 'require_lowercase', 'require_numbers', 'require_special_chars')


@admin.register(Backup)
class BackupAdmin(admin.ModelAdmin):
    list_display = ('type', 'path', 'size', 'status', 'created_at', 'completed_at')
    list_filter = ('type', 'status', 'created_at')
    search_fields = ('path', 'error_message')
    readonly_fields = ('created_at', 'completed_at')

@admin.register(BackupConfig)
class BackupConfigAdmin(admin.ModelAdmin):
    list_display = ('storage_type', 'retention_days', 'updated_at')
    list_filter = ('storage_type', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(BackupSchedule)
class BackupScheduleAdmin(admin.ModelAdmin):
    list_display = ('id', 'frequency', 'cron_expression', 'last_run', 'next_run', 'is_active', 'updated_at')
    list_filter = ('frequency', 'is_active', 'created_at', 'updated_at')
    list_editable = ('frequency', 'cron_expression', 'is_active')
    list_display_links = ('id',)
    readonly_fields = ('last_run', 'next_run', 'created_at', 'updated_at')

@admin.register(UserLog)
class UserLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'ip_address', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('user__email', 'ip_address', 'user_agent')
    readonly_fields = ('created_at',)

@admin.register(AccountRequest)
class AccountRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'phone', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    list_editable = ('status',)
    readonly_fields = ('created_at', 'updated_at')

# Custom Group admin to handle large permission sets more efficiently
class CustomGroupAdminForm(forms.ModelForm):
    """Custom form for Group admin to handle large permission sets"""
    
    class Meta:
        model = Group
        fields = '__all__'
        widgets = {
            'permissions': forms.CheckboxSelectMultiple(),
        }

# Unregister the default Group admin and register our custom one
admin.site.unregister(Group)

@admin.register(Group)
class CustomGroupAdmin(GroupAdmin):
    """Custom Group admin with optimized permission handling"""
    form = CustomGroupAdminForm
    list_display = ('name', 'get_permission_count', 'get_user_count')
    search_fields = ('name',)
    ordering = ('name',)
    
    def get_permission_count(self, obj):
        """Display the number of permissions assigned to this group"""
        return obj.permissions.count()
    get_permission_count.short_description = 'Permissions Count'
    
    def get_user_count(self, obj):
        """Display the number of users in this group"""
        return obj.user_set.count()
    get_user_count.short_description = 'Users Count'
    
    def get_form(self, request, obj=None, **kwargs):
        """Override to add help text and improve UX"""
        form = super().get_form(request, obj, **kwargs)
        if 'permissions' in form.base_fields:
            form.base_fields['permissions'].help_text = (
                "Select permissions for this group. Use Ctrl+Click to select multiple permissions. "
                "Consider using the filter below to narrow down permissions by app or content type."
            )
        return form
