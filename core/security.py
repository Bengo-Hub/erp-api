"""
Security utilities and middleware for enhanced application security.
This module provides comprehensive security features including:
- Security headers management
- Data sanitization and validation
- XSS prevention utilities
- Input validation helpers
- Security audit logging
"""

import re
import html
import logging
from typing import Dict, Any, Optional, List, Set
from django.http import HttpRequest, HttpResponse
from django.conf import settings
from django.utils.html import strip_tags
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
import bleach
from django.db import transaction
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

def _installed_app_labels(prefix: str) -> Set[str]:
    """Return content type app_labels for apps starting with a given namespace prefix (e.g., 'hrm.')."""
    labels: Set[str] = set()
    for app in getattr(settings, 'INSTALLED_APPS', []):
        if app.startswith(prefix):
            parts = app.split('.')
            if len(parts) > 1:
                labels.add(parts[-1])
    return labels

def ensure_rbac_provisioned():
    """
    Ensure standard role groups exist and have permissions assigned based on system modules.
    Centralized function that can be called by middleware and seed scripts.
    """
    # Discover app labels by domain
    hrm_labels = _installed_app_labels('hrm.')
    crm_labels = _installed_app_labels('crm.')
    finance_labels = _installed_app_labels('finance.')
    ecommerce_labels = _installed_app_labels('ecommerce.')
    procurement_labels = _installed_app_labels('procurement.')
    approvals_labels = {'approvals'} if 'approvals' in settings.INSTALLED_APPS else set()
    core_labels = {'core', 'assets', 'business', 'addresses', 'notifications', 'integrations', 'task_management', 'error_handling', 'caching', 'manufacturing'} & {
        app.split('.')[-1] for app in getattr(settings, 'INSTALLED_APPS', [])
    }

    # Build role policies
    role_policies: Dict[str, Dict[str, Any]] = {
        # Only superusers get ALL perms
        'superusers': {'mode': 'ALL'},

        # CTO: full manage on technical/system modules
        'cto': {
            'apps': list(core_labels | approvals_labels | ecommerce_labels | procurement_labels),
            'actions': ['view', 'add', 'change', 'delete']
        },
        # ICT Manager: change/manage on technical/system modules (no delete by default)
        'ict_manager': {
            'apps': list(core_labels | approvals_labels | ecommerce_labels | procurement_labels),
            'actions': ['view', 'add', 'change']
        },
        # CEO: read-only across the system
        'ceo': {'mode': 'READ_ALL'},
        # ICT Officer: read-only on technical/system modules
        'ict_officer': {
            'apps': list(core_labels | approvals_labels | ecommerce_labels | procurement_labels),
            'actions': ['view']
        },
        # HR-focused roles
        'hr_manager': {'apps': list(hrm_labels | approvals_labels), 'actions': ['view', 'add', 'change', 'delete']},
        'hr_assistant': {'apps': list(hrm_labels), 'actions': ['view', 'add', 'change']},
        # Front office
        'receptionist': {'apps': list({'employees', 'attendance', 'leave'} | (crm_labels & {'contacts', 'leads'})), 'actions': ['view', 'add']},
        'secretary': {'apps': list({'employees', 'attendance', 'leave'} | (crm_labels & {'contacts', 'leads'})), 'actions': ['view']},
    }

    # Helper to assign permissions to group
    def assign_perms(group: Group, perms_qs):
        current = set(group.permissions.values_list('id', flat=True))
        to_add = [p for p in perms_qs if p.id not in current]
        if to_add:
            group.permissions.add(*to_add)

    with transaction.atomic():
        for role_name, policy in role_policies.items():
            group, _ = Group.objects.get_or_create(name=role_name)

            if policy.get('mode') == 'ALL':
                perms = Permission.objects.all()
                assign_perms(group, perms)
                continue

            if policy.get('mode') == 'READ_ALL':
                perms = Permission.objects.filter(codename__startswith='view_')
                assign_perms(group, perms)
                continue

            apps = policy.get('apps', [])
            actions = policy.get('actions', ['view'])
            ct_qs = ContentType.objects.filter(app_label__in=apps)
            from django.db.models import Q
            q = Q()
            for action in actions:
                q |= Q(codename__startswith=f"{action}_")
            perms = Permission.objects.filter(content_type__in=ct_qs).filter(q)
            assign_perms(group, perms)

logger = logging.getLogger(__name__)

class SecurityHeaders:
    """Manages security headers for HTTP responses."""
    
    DEFAULT_HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'geolocation=(), microphone=(), camera=()',
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-ancestors 'none';",
    }
    
    @classmethod
    def add_security_headers(cls, response: HttpResponse) -> HttpResponse:
        """Add security headers to the response."""
        for header, value in cls.DEFAULT_HEADERS.items():
            if header not in response:
                response[header] = value
        return response
    
    @classmethod
    def get_csp_header(cls, additional_directives: Optional[Dict[str, List[str]]] = None) -> str:
        """Generate a Content Security Policy header with optional additional directives."""
        csp_parts = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self' https:",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "upgrade-insecure-requests"
        ]
        
        if additional_directives:
            for directive, sources in additional_directives.items():
                csp_parts.append(f"{directive} {' '.join(sources)}")
        
        return "; ".join(csp_parts)

class DataSanitizer:
    """Provides data sanitization and validation utilities."""
    
    # Allowed HTML tags for rich content
    ALLOWED_TAGS = [
        'p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'a', 'img', 'table',
        'thead', 'tbody', 'tr', 'td', 'th'
    ]
    
    # Allowed HTML attributes
    ALLOWED_ATTRIBUTES = {
        'a': ['href', 'title', 'target'],
        'img': ['src', 'alt', 'title', 'width', 'height'],
        'table': ['border', 'cellpadding', 'cellspacing'],
        'td': ['colspan', 'rowspan'],
        'th': ['colspan', 'rowspan']
    }
    
    # Allowed CSS properties
    ALLOWED_STYLES = [
        'color', 'background-color', 'font-size', 'font-weight', 'text-align',
        'margin', 'padding', 'border', 'border-radius', 'width', 'height'
    ]
    
    @classmethod
    def sanitize_html(cls, content: str, allowed_tags: Optional[List[str]] = None) -> str:
        """
        Sanitize HTML content to prevent XSS attacks.
        
        Args:
            content: HTML content to sanitize
            allowed_tags: Custom list of allowed HTML tags
            
        Returns:
            Sanitized HTML content
        """
        if not content:
            return ""
        
        # Use custom allowed tags or default
        tags = allowed_tags or cls.ALLOWED_TAGS
        
        # Sanitize the content
        clean_html = bleach.clean(
            content,
            tags=tags,
            attributes=cls.ALLOWED_ATTRIBUTES,
            styles=cls.ALLOWED_STYLES,
            strip=True
        )
        
        return clean_html
    
    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """
        Sanitize plain text content.
        
        Args:
            text: Text content to sanitize
            
        Returns:
            Sanitized text content
        """
        if not text:
            return ""
        
        # Remove HTML tags
        clean_text = strip_tags(text)
        
        # Escape HTML entities
        clean_text = html.escape(clean_text)
        
        return clean_text
    
    @classmethod
    def sanitize_url(cls, url: str) -> str:
        """
        Sanitize and validate URL.
        
        Args:
            url: URL to sanitize
            
        Returns:
            Sanitized URL or empty string if invalid
        """
        if not url:
            return ""
        
        # Remove whitespace
        url = url.strip()
        
        # Validate URL
        validator = URLValidator()
        try:
            validator(url)
            return url
        except ValidationError:
            logger.warning(f"Invalid URL detected: {url}")
            return ""
    
    @classmethod
    def sanitize_email(cls, email: str) -> str:
        """
        Sanitize and validate email address.
        
        Args:
            email: Email address to sanitize
            
        Returns:
            Sanitized email or empty string if invalid
        """
        if not email:
            return ""
        
        # Remove whitespace and convert to lowercase
        email = email.strip().lower()
        
        # Basic email validation regex
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if re.match(email_pattern, email):
            return email
        else:
            logger.warning(f"Invalid email detected: {email}")
            return ""
    
    @classmethod
    def sanitize_phone(cls, phone: str) -> str:
        """
        Sanitize and validate phone number.
        
        Args:
            phone: Phone number to sanitize
            
        Returns:
            Sanitized phone number or empty string if invalid
        """
        if not phone:
            return ""
        
        # Remove all non-digit characters except + and -
        phone = re.sub(r'[^\d+\-]', '', phone)
        
        # Basic phone validation (at least 10 digits)
        if len(re.sub(r'[^\d]', '', phone)) >= 10:
            return phone
        else:
            logger.warning(f"Invalid phone number detected: {phone}")
            return ""

class InputValidator:
    """Provides input validation utilities."""
    
    @classmethod
    def validate_string_length(cls, value: str, min_length: int = 0, max_length: int = 255) -> bool:
        """Validate string length."""
        if not isinstance(value, str):
            return False
        return min_length <= len(value) <= max_length
    
    @classmethod
    def validate_numeric_range(cls, value: Any, min_value: float = None, max_value: float = None) -> bool:
        """Validate numeric value range."""
        try:
            num_value = float(value)
            if min_value is not None and num_value < min_value:
                return False
            if max_value is not None and num_value > max_value:
                return False
            return True
        except (ValueError, TypeError):
            return False
    
    @classmethod
    def validate_file_extension(cls, filename: str, allowed_extensions: List[str]) -> bool:
        """Validate file extension."""
        if not filename:
            return False
        
        file_extension = filename.lower().split('.')[-1] if '.' in filename else ''
        return file_extension in [ext.lower() for ext in allowed_extensions]
    
    @classmethod
    def validate_file_size(cls, file_size: int, max_size_mb: int) -> bool:
        """Validate file size."""
        max_size_bytes = max_size_mb * 1024 * 1024
        return file_size <= max_size_bytes

class XSSPrevention:
    """XSS prevention utilities."""
    
    @classmethod
    def escape_javascript(cls, value: str) -> str:
        """Escape JavaScript string values."""
        if not value:
            return ""
        
        # Escape JavaScript special characters
        escaped = value.replace('\\', '\\\\')
        escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace("'", "\\'")
        escaped = escaped.replace('\n', '\\n')
        escaped = escaped.replace('\r', '\\r')
        escaped = escaped.replace('\t', '\\t')
        
        return escaped
    
    @classmethod
    def escape_css(cls, value: str) -> str:
        """Escape CSS values."""
        if not value:
            return ""
        
        # Escape CSS special characters
        escaped = value.replace('\\', '\\\\')
        escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace("'", "\\'")
        
        return escaped
    
    @classmethod
    def validate_json(cls, json_string: str) -> bool:
        """Validate JSON string to prevent injection."""
        if not json_string:
            return False
        
        try:
            import json
            json.loads(json_string)
            return True
        except (ValueError, TypeError):
            return False

class SecurityAudit:
    """Security audit logging utilities."""
    
    @classmethod
    def log_security_event(cls, event_type: str, details: Dict[str, Any], user_id: Optional[int] = None):
        """Log security events for audit purposes."""
        log_data = {
            'event_type': event_type,
            'details': details,
            'user_id': user_id,
            'timestamp': str(settings.timezone.now()) if hasattr(settings, 'timezone') else None
        }
        
        logger.warning(f"SECURITY_EVENT: {log_data}")
    
    @classmethod
    def log_suspicious_activity(cls, activity_type: str, details: Dict[str, Any], request: Optional[HttpRequest] = None):
        """Log suspicious activities."""
        log_data = {
            'activity_type': activity_type,
            'details': details,
            'ip_address': request.META.get('REMOTE_ADDR') if request else None,
            'user_agent': request.META.get('HTTP_USER_AGENT') if request else None,
            'timestamp': str(settings.timezone.now()) if hasattr(settings, 'timezone') else None
        }
        
        logger.error(f"SUSPICIOUS_ACTIVITY: {log_data}")

class SecurityMiddleware:
    """Django middleware for enhanced security."""
    
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time RBAC provisioning guard per process
        self._rbac_provisioned = False
    
    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Process request
        # Ensure RBAC groups and permissions are provisioned once
        if not self._rbac_provisioned:
            try:
                ensure_rbac_provisioned()
                self._rbac_provisioned = True
            except Exception as e:
                # Do not block requests if RBAC provisioning fails; just log
                logger.error(f"RBAC provisioning error: {str(e)}", exc_info=True)

        response = self.get_response(request)
        
        # Add security headers
        response = SecurityHeaders.add_security_headers(response)

        # Allow embedding admin pages in iframes for trusted frontends only.
        # The default headers set X-Frame-Options and CSP frame-ancestors to block all framing.
        # Here we relax these ONLY for /admin/* paths so the admin can render inside
        # an iframe (e.g., in the SPA modal) when served by trusted origins.
        try:
            request_path = request.path or ""
        except Exception:
            request_path = ""
        if request_path.startswith("/admin/"):
            # Compute allowed ancestors from settings
            allowed_ancestors: List[str] = ["'self'"]
            for origin in getattr(settings, "CORS_ALLOWED_ORIGINS", []) or []:
                if origin not in allowed_ancestors:
                    allowed_ancestors.append(origin)
            for origin in getattr(settings, "CSRF_TRUSTED_ORIGINS", []) or []:
                if origin not in allowed_ancestors:
                    allowed_ancestors.append(origin)

            # Remove X-Frame-Options to let CSP control the embedding policy.
            if "X-Frame-Options" in response:
                try:
                    del response["X-Frame-Options"]
                except Exception:
                    # If deletion fails for any reason, overwrite with a permissive value
                    # so that modern browsers prefer CSP's frame-ancestors.
                    response["X-Frame-Options"] = "ALLOW-FROM " + " ".join(allowed_ancestors)

            # Rebuild CSP while overriding any existing frame-ancestors directive.
            existing_csp = response.get(
                "Content-Security-Policy",
                SecurityHeaders.get_csp_header()
            )
            # Strip any existing frame-ancestors directives
            csp_parts: List[str] = [p.strip() for p in existing_csp.split(";") if p.strip()]
            csp_parts = [p for p in csp_parts if not p.lower().startswith("frame-ancestors")]
            # Add our allowed ancestors
            csp_parts.append(f"frame-ancestors {' '.join(allowed_ancestors)}")
            response["Content-Security-Policy"] = "; ".join(csp_parts)
        
        # Log suspicious activities
        self._check_suspicious_activity(request)
        
        return response
    
    def _installed_app_labels(self, prefix: str) -> Set[str]:
        """Return content type app_labels for apps starting with a given namespace prefix (e.g., 'hrm.')."""
        labels: Set[str] = set()
        for app in getattr(settings, 'INSTALLED_APPS', []):
            if app.startswith(prefix):
                # ContentType.app_label is the final component (django app label)
                parts = app.split('.')
                if len(parts) > 1:
                    labels.add(parts[-1])
        return labels

    def _ensure_rbac_provisioned(self):
        """
        Ensure standard role groups exist and have permissions assigned based on system modules.
        Roles: cto, ceo, hr_manager, hr_assistant, receptionist, ict_manager, it_officer, secretary
        """
        # Discover app labels by domain
        hrm_labels = self._installed_app_labels('hrm.')
        crm_labels = self._installed_app_labels('crm.')
        finance_labels = self._installed_app_labels('finance.')
        ecommerce_labels = self._installed_app_labels('ecommerce.')
        procurement_labels = self._installed_app_labels('procurement.')
        approvals_labels = {'approvals'} if 'approvals' in settings.INSTALLED_APPS else set()
        core_labels = {'core', 'assets', 'business', 'addresses', 'notifications', 'integrations', 'task_management', 'error_handling', 'caching', 'manufacturing'} & {
            app.split('.')[-1] for app in getattr(settings, 'INSTALLED_APPS', [])
        }

        # Build role policies
        role_policies: Dict[str, Dict[str, Any]] = {
            # Only superusers get ALL perms
            'superusers': {'mode': 'ALL'},

            # CTO: full manage on technical/system modules (no finance, hrm, etc.)
            'cto': {
                'apps': list(core_labels | approvals_labels | ecommerce_labels | procurement_labels),
                'actions': ['view', 'add', 'change', 'delete']
            },
            # ICT Manager: change/manage on technical/system modules (no delete by default)
            'ict_manager': {
                'apps': list(core_labels | approvals_labels | ecommerce_labels | procurement_labels),
                'actions': ['view', 'add', 'change']
            },
            # CEO: read-only across the system
            'ceo': {'mode': 'READ_ALL'},
            # IT Officer: read-only on technical/system modules
            'ict_officer': {
                'apps': list(core_labels | approvals_labels | ecommerce_labels | procurement_labels),
                'actions': ['view']
            },
            # HR-focused roles
            'hr_manager': {'apps': list(hrm_labels | approvals_labels), 'actions': ['view', 'add', 'change', 'delete']},
            'hr_assistant': {'apps': list(hrm_labels), 'actions': ['view', 'add', 'change']},
            # Front office
            'receptionist': {'apps': list({'employees', 'attendance', 'leave'} | (crm_labels & {'contacts', 'leads'})), 'actions': ['view', 'add']},
            'secretary': {'apps': list({'employees', 'attendance', 'leave'} | (crm_labels & {'contacts', 'leads'})), 'actions': ['view']},
        }

        # Helper to assign permissions to group
        def assign_perms(group: Group, perms_qs):
            current = set(group.permissions.values_list('id', flat=True))
            to_add = [p for p in perms_qs if p.id not in current]
            if to_add:
                group.permissions.add(*to_add)

        with transaction.atomic():
            for role_name, policy in role_policies.items():
                group, _ = Group.objects.get_or_create(name=role_name)

                if policy.get('mode') == 'ALL':
                    perms = Permission.objects.all()
                    assign_perms(group, perms)
                    continue

                if policy.get('mode') == 'READ_ALL':
                    perms = Permission.objects.filter(codename__startswith='view_')
                    assign_perms(group, perms)
                    continue

                apps = policy.get('apps', [])
                actions = policy.get('actions', ['view'])
                # Fetch content types for selected app labels
                ct_qs = ContentType.objects.filter(app_label__in=apps)
                codenames = [f"{action}_" for action in actions]  # prefix match
                perms = Permission.objects.filter(content_type__in=ct_qs).filter(
                    # match action prefixes
                    # Since we don't have OR with startswith list directly, use Q union
                )
                # Build OR query dynamically
                from django.db.models import Q
                q = Q()
                for pref in codenames:
                    q |= Q(codename__startswith=pref)
                perms = Permission.objects.filter(content_type__in=ct_qs).filter(q)
                assign_perms(group, perms)

    def _check_suspicious_activity(self, request: HttpRequest):
        """Check for suspicious activities in the request."""
        suspicious_patterns = [
            r'<script[^>]*>',
            r'javascript:',
            r'vbscript:',
            r'on\w+\s*=',
            r'<iframe[^>]*>',
            r'<object[^>]*>',
            r'<embed[^>]*>'
        ]
        
        # Check URL parameters
        for param_name, param_value in request.GET.items():
            if isinstance(param_value, str):
                for pattern in suspicious_patterns:
                    if re.search(pattern, param_value, re.IGNORECASE):
                        SecurityAudit.log_suspicious_activity(
                            'suspicious_url_parameter',
                            {
                                'parameter': param_name,
                                'value': param_value,
                                'pattern': pattern
                            },
                            request
                        )
        
        # Check POST data
        if request.method == 'POST':
            for param_name, param_value in request.POST.items():
                if isinstance(param_value, str):
                    for pattern in suspicious_patterns:
                        if re.search(pattern, param_value, re.IGNORECASE):
                            SecurityAudit.log_suspicious_activity(
                                'suspicious_post_data',
                                {
                                    'parameter': param_name,
                                    'value': param_value,
                                    'pattern': pattern
                                },
                                request
                            )
