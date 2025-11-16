"""
Security module for authentication management.
Handles 2FA, account lockout, security monitoring, and audit logging.
"""

import pyotp
from qrcode.main import QRCode
import base64
import io
import logging
from datetime import datetime, timedelta
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import authenticate, login
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
import re
from addresses.models import AddressBook
from business.models import Branch, Bussiness
from hrm.employees.models import Employee, HRDetails
from rest_framework.authtoken.models import Token

User = get_user_model()
logger = logging.getLogger(__name__)

class TwoFactorAuth(models.Model):
    """Two-Factor Authentication model"""
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='two_factor_auth')
    secret_key = models.CharField(max_length=32, unique=True)
    is_enabled = models.BooleanField(default=False)
    backup_codes = models.JSONField(default=list)
    last_used = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Two-Factor Authentication"
        verbose_name_plural = "Two-Factor Authentication"
    
    def __str__(self):
        return f"2FA for {self.user.email}"
    
    def generate_secret_key(self):
        """Generate a new secret key for TOTP"""
        return pyotp.random_base32()
    
    def generate_qr_code(self, email):
        """Generate QR code for authenticator app"""
        totp = pyotp.TOTP(self.secret_key)
        provisioning_uri = totp.provisioning_uri(
            name=email,
            issuer_name="Bengo ERP"
        )
        
        # Generate QR code
        qr = QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    
    def verify_code(self, code):
        """Verify TOTP code"""
        if not self.is_enabled:
            return False
        
        totp = pyotp.TOTP(self.secret_key)
        is_valid = totp.verify(code, valid_window=1)  # Allow 30-second window
        
        if is_valid:
            self.last_used = timezone.now()
            self.save()
        
        return is_valid
    
    def generate_backup_codes(self, count=8):
        """Generate backup codes for account recovery"""
        import secrets
        codes = []
        for _ in range(count):
            code = secrets.token_hex(4).upper()  # 8-character hex code
            codes.append(code)
        
        self.backup_codes = codes
        self.save()
        return codes
    
    def verify_backup_code(self, code):
        """Verify backup code and remove it if valid"""
        if code in self.backup_codes:
            self.backup_codes.remove(code)
            self.save()
            return True
        return False

class AccountLockout(models.Model):
    """Account lockout model for failed login attempts"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lockouts')
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    failed_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Account Lockout"
        verbose_name_plural = "Account Lockouts"
        unique_together = ['user', 'ip_address']
    
    def __str__(self):
        return f"Lockout for {self.user.email} from {self.ip_address}"
    
    def increment_failed_attempts(self):
        """Increment failed login attempts"""
        self.failed_attempts += 1
        self.updated_at = timezone.now()
        
        # Check if account should be locked
        max_attempts = getattr(settings, 'MAX_LOGIN_ATTEMPTS', 5)
        lockout_duration = getattr(settings, 'LOCKOUT_DURATION_MINUTES', 30)
        
        if self.failed_attempts >= max_attempts:
            self.is_locked = True
            self.locked_until = timezone.now() + timedelta(minutes=lockout_duration)
            
            # Log security event
            SecurityAuditLog.objects.create(
                user=self.user,
                event_type='account_locked',
                ip_address=self.ip_address,
                user_agent=self.user_agent,
                details={
                    'failed_attempts': self.failed_attempts,
                    'locked_until': self.locked_until.isoformat(),
                    'reason': 'Too many failed login attempts'
                }
            )
        
        self.save()
    
    def reset_failed_attempts(self):
        """Reset failed attempts after successful login"""
        self.failed_attempts = 0
        self.is_locked = False
        self.locked_until = None
        self.updated_at = timezone.now()
        self.save()
    
    def is_currently_locked(self):
        """Check if account is currently locked"""
        if not self.is_locked:
            return False
        
        if self.locked_until and timezone.now() > self.locked_until:
            # Auto-unlock after lockout period
            self.is_locked = False
            self.locked_until = None
            self.save()
            return False
        
        return True
    
    def get_remaining_lockout_time(self):
        """Get remaining lockout time in minutes"""
        if not self.is_locked or not self.locked_until:
            return 0
        
        remaining = self.locked_until - timezone.now()
        return max(0, int(remaining.total_seconds() / 60))

class SecurityAuditLog(models.Model):
    """Security audit log for tracking security events"""
    
    EVENT_TYPES = [
        ('login_success', 'Login Success'),
        ('login_failed', 'Login Failed'),
        ('logout', 'Logout'),
        ('password_change', 'Password Change'),
        ('password_reset', 'Password Reset'),
        ('account_locked', 'Account Locked'),
        ('account_unlocked', 'Account Unlocked'),
        ('2fa_enabled', '2FA Enabled'),
        ('2fa_disabled', '2FA Disabled'),
        ('2fa_used', '2FA Used'),
        ('suspicious_activity', 'Suspicious Activity'),
        ('admin_action', 'Admin Action'),
        ('data_access', 'Data Access'),
        ('data_modification', 'Data Modification'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='security_logs', null=True, blank=True)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    details = models.JSONField(default=dict)
    severity = models.CharField(max_length=20, choices=[
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], default='low')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Security Audit Log"
        verbose_name_plural = "Security Audit Logs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'event_type', 'created_at']),
            models.Index(fields=['ip_address', 'created_at']),
            models.Index(fields=['severity', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.event_type} - {self.user.email if self.user else 'Anonymous'} - {self.created_at}"
    
    @classmethod
    def log_event(cls, event_type, user=None, ip_address=None, user_agent=None, details=None, severity='low'):
        """Log a security event"""
        try:
            log_entry = cls.objects.create(
                user=user,
                event_type=event_type,
                ip_address=ip_address or '0.0.0.0',
                user_agent=user_agent or '',
                details=details or {},
                severity=severity
            )
            
            # Log to console for immediate visibility
            logger.info(f"Security Event: {event_type} - User: {user.email if user else 'Anonymous'} - IP: {ip_address}")
            
            return log_entry
        except Exception as e:
            logger.error(f"Failed to log security event: {e}")
            return None

class SecuritySettings(models.Model):
    """Global security settings"""
    
    # Password policies
    min_password_length = models.PositiveIntegerField(default=8)
    require_uppercase = models.BooleanField(default=True)
    require_lowercase = models.BooleanField(default=True)
    require_numbers = models.BooleanField(default=True)
    require_special_chars = models.BooleanField(default=True)
    password_expiry_days = models.PositiveIntegerField(default=90)
    
    # Account lockout settings
    max_login_attempts = models.PositiveIntegerField(default=5)
    lockout_duration_minutes = models.PositiveIntegerField(default=30)
    
    # Session settings
    session_timeout_minutes = models.PositiveIntegerField(default=480)  # 8 hours
    max_concurrent_sessions = models.PositiveIntegerField(default=3)
    
    # 2FA settings
    require_2fa_for_admins = models.BooleanField(default=True)
    require_2fa_for_sensitive_operations = models.BooleanField(default=True)
    
    # Security monitoring
    enable_security_alerts = models.BooleanField(default=True)
    alert_email_addresses = models.JSONField(default=list)
    
    # IP restrictions
    allowed_ip_ranges = models.JSONField(default=list)
    block_suspicious_ips = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Security Settings"
        verbose_name_plural = "Security Settings"
    
    def __str__(self):
        return f"Security Settings (Updated: {self.updated_at})"
    
    @classmethod
    def get_settings(cls):
        """Get current security settings"""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

class SecurityService:
    """Service class for security operations"""
    
    @staticmethod
    def validate_password(password, user=None):
        """Validate password against security policies"""
        settings = SecuritySettings.get_settings()
        errors = []
        
        # Check minimum length
        if len(password) < settings.min_password_length:
            errors.append(f"Password must be at least {settings.min_password_length} characters long")
        
        # Check character requirements
        if settings.require_uppercase and not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter")
        
        if settings.require_lowercase and not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter")
        
        if settings.require_numbers and not re.search(r'\d', password):
            errors.append("Password must contain at least one number")
        
        if settings.require_special_chars and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append("Password must contain at least one special character")
        
        # Check against user's previous passwords (if user provided)
        if user:
            # This would require implementing password history tracking
            pass
        
        return errors
    
    @staticmethod
    def check_account_lockout(user, ip_address):
        """Check if account is locked for the given IP"""
        try:
            lockout = AccountLockout.objects.get(user=user, ip_address=ip_address)
            return lockout.is_currently_locked()
        except AccountLockout.DoesNotExist:
            return False
    
    @staticmethod
    def record_failed_login(user, ip_address, user_agent):
        """Record a failed login attempt"""
        lockout, created = AccountLockout.objects.get_or_create(
            user=user,
            ip_address=ip_address,
            defaults={'user_agent': user_agent}
        )
        
        if not created:
            lockout.user_agent = user_agent
        
        lockout.increment_failed_attempts()
        
        # Log the failed attempt
        SecurityAuditLog.log_event(
            event_type='login_failed',
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            details={'failed_attempts': lockout.failed_attempts},
            severity='medium'
        )
    
    @staticmethod
    def record_successful_login(user, ip_address, user_agent):
        """Record a successful login"""
        # Reset failed attempts
        try:
            lockout = AccountLockout.objects.get(user=user, ip_address=ip_address)
            lockout.reset_failed_attempts()
        except AccountLockout.DoesNotExist:
            pass
        
        # Log successful login
        SecurityAuditLog.log_event(
            event_type='login_success',
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            severity='low'
        )
    
    @staticmethod
    def setup_2fa(user):
        """Set up 2FA for a user"""
        # Generate secret key
        secret_key = pyotp.random_base32()
        
        # Create or update 2FA record
        two_fa, created = TwoFactorAuth.objects.get_or_create(
            user=user,
            defaults={'secret_key': secret_key}
        )
        
        if not created:
            two_fa.secret_key = secret_key
            two_fa.save()
        
        # Generate QR code
        qr_code = two_fa.generate_qr_code(user.email)
        
        # Generate backup codes
        backup_codes = two_fa.generate_backup_codes()
        
        return {
            'secret_key': secret_key,
            'qr_code': qr_code,
            'backup_codes': backup_codes
        }
    
    @staticmethod
    def verify_2fa_code(user, code):
        """Verify 2FA code"""
        try:
            two_fa = TwoFactorAuth.objects.get(user=user, is_enabled=True)
            
            # Try TOTP code first
            if two_fa.verify_code(code):
                return True
            
            # Try backup code
            if two_fa.verify_backup_code(code):
                return True
            
            return False
        except TwoFactorAuth.DoesNotExist:
            return False
    
    @staticmethod
    def enable_2fa(user, code):
        """Enable 2FA for a user"""
        try:
            two_fa = TwoFactorAuth.objects.get(user=user)
            
            if two_fa.verify_code(code):
                two_fa.is_enabled = True
                two_fa.save()
                
                # Log the event
                SecurityAuditLog.log_event(
                    event_type='2fa_enabled',
                    user=user,
                    severity='medium'
                )
                
                return True
            
            return False
        except TwoFactorAuth.DoesNotExist:
            return False
    
    @staticmethod
    def disable_2fa(user):
        """Disable 2FA for a user"""
        try:
            two_fa = TwoFactorAuth.objects.get(user=user)
            two_fa.is_enabled = False
            two_fa.save()
            
            # Log the event
            SecurityAuditLog.log_event(
                event_type='2fa_disabled',
                user=user,
                severity='medium'
            )
            
            return True
        except TwoFactorAuth.DoesNotExist:
            return False
    
    @staticmethod
    def get_security_summary(user):
        """Get security summary for a user"""
        try:
            two_fa = TwoFactorAuth.objects.get(user=user)
        except TwoFactorAuth.DoesNotExist:
            two_fa = None
        
        # Get recent security events
        recent_events = SecurityAuditLog.objects.filter(user=user).order_by('-created_at')[:10]
        
        # Get active lockouts
        active_lockouts = AccountLockout.objects.filter(user=user, is_locked=True)
        
        return {
            'two_factor_enabled': two_fa.is_enabled if two_fa else False,
            'last_2fa_used': two_fa.last_used if two_fa else None,
            'recent_events': list(recent_events.values('event_type', 'ip_address', 'created_at')),
            'active_lockouts': list(active_lockouts.values('ip_address', 'locked_until')),
            'backup_codes_remaining': len(two_fa.backup_codes) if two_fa else 0
        }

# ==========================
# API Views (consolidated)
# ==========================

class TwoFactorAuthView(APIView):
    """Two-Factor Authentication endpoints"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            two_fa = TwoFactorAuth.objects.filter(user=user).first()
            if two_fa:
                return Response({
                    'is_enabled': two_fa.is_enabled,
                    'last_used': two_fa.last_used,
                    'backup_codes_remaining': len(two_fa.backup_codes),
                    'created_at': two_fa.created_at
                })
            else:
                return Response({
                    'is_enabled': False,
                    'last_used': None,
                    'backup_codes_remaining': 0,
                    'created_at': None
                })
        except Exception:
            return Response({'error': 'Failed to get 2FA status'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        try:
            user = request.user
            existing_2fa = TwoFactorAuth.objects.filter(user=user, is_enabled=True).first()
            if existing_2fa:
                return Response({'error': '2FA is already enabled'}, status=status.HTTP_400_BAD_REQUEST)
            setup_data = SecurityService.setup_2fa(user)
            return Response({
                'message': '2FA setup successful',
                'qr_code': setup_data['qr_code'],
                'backup_codes': setup_data['backup_codes'],
                'secret_key': setup_data['secret_key']
            })
        except Exception:
            return Response({'error': 'Failed to set up 2FA'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TwoFactorVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            code = request.data.get('code')
            if not code:
                return Response({'error': '2FA code is required'}, status=status.HTTP_400_BAD_REQUEST)
            user = request.user
            if SecurityService.verify_2fa_code(user, code):
                if SecurityService.enable_2fa(user, code):
                    return Response({'message': '2FA enabled successfully', 'is_enabled': True})
                else:
                    return Response({'error': 'Failed to enable 2FA'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({'error': 'Invalid 2FA code'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({'error': 'Failed to verify 2FA code'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TwoFactorDisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            if SecurityService.disable_2fa(user):
                return Response({'message': '2FA disabled successfully', 'is_enabled': False})
            else:
                return Response({'error': 'Failed to disable 2FA'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({'error': 'Failed to disable 2FA'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TwoFactorBackupCodesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            try:
                two_fa = TwoFactorAuth.objects.get(user=user, is_enabled=True)
                backup_codes = two_fa.generate_backup_codes()
                return Response({'message': 'New backup codes generated', 'backup_codes': backup_codes})
            except TwoFactorAuth.DoesNotExist:
                return Response({'error': '2FA is not enabled'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({'error': 'Failed to generate backup codes'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EnhancedLoginView(APIView):
    """Enhanced login with 2FA and account lockout support"""
    permission_classes = [AllowAny]
    
    # Exempt from CSRF for API login
    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        try:
            email = request.data.get('email')
            password = request.data.get('password')
            two_fa_code = request.data.get('two_fa_code')
            if not email or not password:
                return Response({'error': 'Email and password are required'}, status=status.HTTP_400_BAD_REQUEST)

            ip_address = self.get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')

            try:
                user_found = User.objects.get(email=email)
            except User.DoesNotExist:
                logger.warning("Login failed: unknown email '%s' from %s", email, ip_address)
                return Response({'success': False, 'error': {'type': 'InvalidCredentials', 'message': 'Invalid credentials'}}, status=status.HTTP_401_UNAUTHORIZED)

            if SecurityService.check_account_lockout(user_found, ip_address):
                lockout = AccountLockout.objects.get(user=user_found, ip_address=ip_address)
                remaining_time = lockout.get_remaining_lockout_time()
                logger.info("Login blocked due to lockout for user '%s' from %s (remaining %s min)", email, ip_address, remaining_time)
                return Response({'success': False, 'error': {'type': 'AccountLocked', 'message': 'Account is temporarily locked', 'remaining_minutes': remaining_time, 'locked_until': lockout.locked_until}}, status=status.HTTP_423_LOCKED)

            auth_user = authenticate(request, username=email, password=password)
            if auth_user is None:
                # Use the looked-up user record for failed attempt tracking
                SecurityService.record_failed_login(user_found, ip_address, user_agent)
                logger.warning("Login failed: bad password for '%s' from %s", email, ip_address)
                return Response({'success': False, 'error': {'type': 'InvalidCredentials', 'message': 'Invalid credentials'}}, status=status.HTTP_401_UNAUTHORIZED)

            try:
                two_fa = TwoFactorAuth.objects.get(user=auth_user, is_enabled=True)
                requires_2fa = True
            except TwoFactorAuth.DoesNotExist:
                requires_2fa = False

            if requires_2fa:
                if not two_fa_code:
                    logger.info("2FA required for '%s' from %s", email, ip_address)
                    return Response({'success': False, 'error': {'type': 'TwoFactorRequired', 'message': '2FA code required'}, 'requires_2fa': True}, status=status.HTTP_401_UNAUTHORIZED)
                if not SecurityService.verify_2fa_code(auth_user, two_fa_code):
                    SecurityService.record_failed_login(auth_user, ip_address, user_agent)
                    logger.warning("2FA verification failed for '%s' from %s", email, ip_address)
                    return Response({'success': False, 'error': {'type': 'InvalidTwoFactorCode', 'message': 'Invalid 2FA code'}, 'requires_2fa': True}, status=status.HTTP_401_UNAUTHORIZED)

            login(request, auth_user)
            SecurityService.record_successful_login(auth_user, ip_address, user_agent)

            # Determine if password change is required (first login or expired)
            from authmanagement.models import PasswordPolicy
            from django.utils import timezone
            policy = PasswordPolicy.objects.first()
            if policy is None:
                policy = PasswordPolicy.objects.create()  # defaults

            password_change_required = False
            password_change_reason = None
            expires_on = None

            # First-login enforcement
            if getattr(policy, 'require_password_change_on_first_login', True):
                if getattr(auth_user, 'password_changed_at', None) is None and getattr(auth_user, 'last_login', None) is None:
                    password_change_required = True
                    password_change_reason = 'first_login'

            # Expiry enforcement
            try:
                if getattr(policy, 'enforce_password_expiry', True) and policy.password_expiry_days > 0:
                    reference_time = getattr(auth_user, 'password_changed_at', None) or getattr(auth_user, 'date_joined', None)
                    if reference_time is not None:
                        expires_on = reference_time + timezone.timedelta(days=policy.password_expiry_days)
                        if timezone.now() >= expires_on:
                            password_change_required = True
                            password_change_reason = 'password_expired'
            except Exception:
                pass

            # Build extended response (business, addresses, roles, permissions)
            # Addresses
            try:
                addresses = list(AddressBook.objects.filter(user=auth_user).values(
                    "id",
                    "first_name",
                    "last_name",
                    "phone",
                    "other_phone",
                    "city",
                    "state",
                    "postal_code",
                    "country",
                    "is_pickup_address",
                    "address_label",
                    "is_default_shipping",
                    "is_default_billing",
                    "pickup_station_id"
                ))
            except Exception:
                addresses = []

            # Business details
            try:
                # First try to get business as owner
                owned_businesses = Bussiness.objects.filter(owner=auth_user)
                if owned_businesses.exists():
                    business_obj = owned_businesses.first()
                    # Get the main branch for this business
                    main_branch = Branch.objects.filter(business=business_obj, is_main_branch=True).first()
                    if not main_branch:
                        main_branch = Branch.objects.filter(business=business_obj).first()
                    
                    if main_branch:
                        business = {
                            'id': business_obj.id,
                            'business__name': business_obj.name,
                            'name': main_branch.name,
                            'branch_code': main_branch.branch_code,
                            'country': str(main_branch.location.country) if main_branch.location and main_branch.location.country else 'KE',
                            'city': main_branch.location.city if main_branch.location else 'Kisumu',
                            'postal_code': main_branch.location.postal_code if main_branch.location else '567',
                            'zip_code': main_branch.location.zip_code if main_branch.location else '40100',
                            'contact_number': main_branch.contact_number,
                            'alternate_contact_number': main_branch.alternate_contact_number,
                            'email': main_branch.email,
                            'website': main_branch.location.website if main_branch.location else 'codevertexitsolutions.com',
                            'business__logo': business_obj.logo.url if business_obj.logo else None,
                            'business__watermarklogo': business_obj.watermarklogo.url if business_obj.watermarklogo else None,
                            'branding_settings': business_obj.get_branding_settings()
                        }
                    else:
                        business = None
                else:
                    # Try to get business as employee
                    employee = Employee.objects.filter(user=auth_user).first()
                    if employee and employee.organisation:
                        business_obj = employee.organisation
                        # Get the employee's assigned branch or main branch
                        hr_details = HRDetails.objects.filter(employee=employee).first()
                        if hr_details and hr_details.branch:
                            main_branch = hr_details.branch
                        else:
                            main_branch = Branch.objects.filter(business=business_obj, is_main_branch=True).first()
                            if not main_branch:
                                main_branch = Branch.objects.filter(business=business_obj).first()
                        
                        if main_branch:
                            business = {
                                'id': business_obj.id,
                                'business__name': business_obj.name,
                                'name': main_branch.name,
                                'branch_code': main_branch.branch_code,
                                'country': str(main_branch.location.country) if main_branch.location and main_branch.location.country else 'KE',
                                'city': main_branch.location.city if main_branch.location else 'Kisumu',
                                'postal_code': main_branch.location.postal_code if main_branch.location else '567',
                                'zip_code': main_branch.location.zip_code if main_branch.location else '40100',
                                'contact_number': main_branch.contact_number,
                                'alternate_contact_number': main_branch.alternate_contact_number,
                                'email': main_branch.email,
                                'website': main_branch.location.website if main_branch.location else 'codevertexitsolutions.com',
                                'business__logo': business_obj.logo.url if business_obj.logo else None,
                                'business__watermarklogo': business_obj.watermarklogo.url if business_obj.watermarklogo else None,
                                'branding_settings': business_obj.get_branding_settings()
                            }
                        else:
                            business = None
                    else:
                        business = None
            except Exception as e:
                logger.error(f"Error retrieving business details for user {auth_user.email}: {str(e)}")
                business = None

            # Token and permissions
            token, _ = Token.objects.get_or_create(user=auth_user)
            try:
                permissions = []
                for group in auth_user.groups.all():
                    permissions.extend([perm.codename for perm in group.permissions.all()])
                permissions = sorted(list(set(permissions)))
            except Exception:
                permissions = []

            # Safe user payload
            middle_name = getattr(auth_user, 'middle_name', '') or ''
            pic_url = None
            pic_field = getattr(auth_user, 'pic', None)
            if pic_field and getattr(pic_field, 'name', None):
                try:
                    pic_url = pic_field.url
                except Exception:
                    pic_url = None
            if not pic_url:
                pic_url = (settings.MEDIA_URL or '/media/') + 'userprofiles/default.png'
            user_payload = {
                "username": getattr(auth_user, 'username', ''),
                "email": getattr(auth_user, 'email', ''),
                "phone": getattr(auth_user, 'phone', None),
                "pic": pic_url,
                "fullname": f"{getattr(auth_user, 'first_name', '') or ''} {middle_name} {getattr(auth_user, 'last_name', '') or ''}".strip(),
                "id": getattr(auth_user, 'pk', None),
                "token": token.key,
                "permissions": permissions,
            }

            # Employee mapping
            try:
                emp = Employee.objects.filter(user=auth_user).only('id').first()
                user_payload["employee_id"] = emp.id if emp else None
            except Exception:
                user_payload["employee_id"] = None

            return Response({
                'message': 'Login successful',
                'user': user_payload,
                'business': business,
                'addresses': addresses,
                'roles': [group.name for group in auth_user.groups.all()] if hasattr(auth_user, 'groups') else [],
                'requires_2fa': False,
                'password_change_required': password_change_required,
                'password_change_reason': password_change_reason,
                'password_expires_on': expires_on
            })
        except Exception as e:
            safe_email = locals().get('email', 'unknown')
            logger.exception("Unhandled error during login for '%s' from %s", safe_email, request.META.get('REMOTE_ADDR'))
            if settings.DEBUG:
                return Response({'success': False, 'error': {'type': e.__class__.__name__, 'message': str(e)}}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return Response({'success': False, 'error': {'type': 'ServerError', 'message': 'Login failed'}}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class SecurityDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            security_summary = SecurityService.get_security_summary(user)
            settings_obj = SecuritySettings.get_settings()
            return Response({
                'security_summary': security_summary,
                'settings': {
                    'max_login_attempts': settings_obj.max_login_attempts,
                    'lockout_duration_minutes': settings_obj.lockout_duration_minutes,
                    'session_timeout_minutes': settings_obj.session_timeout_minutes,
                    'require_2fa_for_admins': settings_obj.require_2fa_for_admins,
                    'require_2fa_for_sensitive_operations': settings_obj.require_2fa_for_sensitive_operations
                }
            })
        except Exception:
            return Response({'error': 'Failed to get security summary'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SecurityAuditLogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            logs = SecurityAuditLog.objects.filter(user=request.user).order_by('-created_at')[:50]
            return Response(list(logs.values()))
        except Exception:
            return Response({'error': 'Failed to retrieve audit logs'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def unlock_account(request):
    try:
        user_id = request.data.get('user_id')
        ip_address = request.data.get('ip_address')
        if not user_id or not ip_address:
            return Response({'error': 'user_id and ip_address are required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(id=user_id)
            lockout = AccountLockout.objects.get(user=user, ip_address=ip_address)
            lockout.is_locked = False
            lockout.failed_attempts = 0
            lockout.locked_until = None
            lockout.save()
            SecurityAuditLog.log_event(event_type='account_unlocked', user=user, ip_address=ip_address, severity='medium')
            return Response({'message': 'Account unlocked successfully'})
        except (User.DoesNotExist, AccountLockout.DoesNotExist):
            return Response({'error': 'Lockout record not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception:
        return Response({'error': 'Failed to unlock account'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def security_settings(request):
    try:
        settings_obj = SecuritySettings.get_settings()
        return Response({
            'password_policies': {
                'min_password_length': settings_obj.min_password_length,
                'require_uppercase': settings_obj.require_uppercase,
                'require_lowercase': settings_obj.require_lowercase,
                'require_numbers': settings_obj.require_numbers,
                'require_special_chars': settings_obj.require_special_chars,
                'password_expiry_days': settings_obj.password_expiry_days
            },
            'account_lockout': {
                'max_login_attempts': settings_obj.max_login_attempts,
                'lockout_duration_minutes': settings_obj.lockout_duration_minutes
            },
            'session_settings': {
                'session_timeout_minutes': settings_obj.session_timeout_minutes,
                'max_concurrent_sessions': settings_obj.max_concurrent_sessions
            },
            'two_factor_auth': {
                'require_2fa_for_admins': settings_obj.require_2fa_for_admins,
                'require_2fa_for_sensitive_operations': settings_obj.require_2fa_for_sensitive_operations
            }
        })
    except Exception:
        return Response({'error': 'Failed to get security settings'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
