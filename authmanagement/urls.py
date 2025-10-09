from rest_framework.routers import DefaultRouter
from django.urls import path,include
from . views import *
from .security import (
    TwoFactorAuthView, TwoFactorVerifyView, TwoFactorDisableView,
    TwoFactorBackupCodesView, EnhancedLoginView, SecurityDashboardView,
    SecurityAuditLogView, unlock_account, security_settings
)

router = DefaultRouter()
#router.register('listusers', UserViewSet)
router.register('hodusers', HODUserViewSet, basename='hodusers')

urlpatterns = [
    path('', include(router.urls)),
    path("register/", RegistrationView.as_view(), name="user_create"),
    path('register/confirm-email/<str:uidb64>/<str:token>/',
         EmailConfirmView.as_view(), name='email_confirm'),
    path('confirm-email-success',email_confirm_success,name='email_confirm_success'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('password-reset-confirm/<str:uidb64>/<str:token>/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path("logout/", LogOutApiView.as_view(), name="logout_api"),
    path('listusers/', UserViewSet.as_view(), name='users'),
    path('listusers/<int:pk>/',
         UserViewSet.as_view(), name='update_users'),
    path('password-policy/', PasswordPolicyView.as_view(), name='password_policy'),
    path('backups/', BackupView.as_view(), name='backup_list'),
    path('backups/config/', BackupConfigView.as_view(), name='backup_config'),
    path('roles/', RoleView.as_view(), name='role_list'),
    path('roles/<int:pk>/', RoleView.as_view(), name='role_detail'),
    path('permissions/', PermissionView.as_view(), name='permission_list'),
    path('permissions/<int:pk>/', PermissionView.as_view(), name='permission_detail'),

    # Security URLs (single login endpoint at /api/v1/auth/login/)
    path('security/login/', EnhancedLoginView.as_view(), name='enhanced_login'),
    path('security/2fa/', TwoFactorAuthView.as_view(), name='two_factor_auth'),
    path('security/2fa/verify/', TwoFactorVerifyView.as_view(), name='two_factor_verify'),
    path('security/2fa/disable/', TwoFactorDisableView.as_view(), name='two_factor_disable'),
    path('security/2fa/backup-codes/', TwoFactorBackupCodesView.as_view(), name='two_factor_backup_codes'),
    path('security/dashboard/', SecurityDashboardView.as_view(), name='security_dashboard'),
    path('security/audit-logs/', SecurityAuditLogView.as_view(), name='security_audit_logs'),
    # path('security/admin/', AdminSecurityView.as_view(), name='admin_security'),
    path('security/unlock-account/', unlock_account, name='unlock_account'),
    path('security/settings/', security_settings, name='security_settings'),
]
