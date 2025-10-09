"""
Centralized error handling for all ERP modules
"""
import logging
import traceback
import uuid
from typing import Dict, Any, Optional
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
from django.http import HttpRequest
import re

from .models import Error, ErrorLog, ErrorPattern, ErrorSeverity, ErrorCategory, ErrorStatus

User = get_user_model()

logger = logging.getLogger('ditapi_logger')


class ErrorHandler:
    """
    Centralized error handler for all ERP modules
    """
    
    def __init__(self):
        self.patterns = self._load_error_patterns()
    
    def _load_error_patterns(self):
        """Load error patterns for automatic classification"""
        try:
            return ErrorPattern.objects.filter(is_active=True)
        except Exception:
            return []
    
    def handle_error(self, exception: Exception, context: Dict[str, Any] = None, 
                    request: HttpRequest = None, user: User = None) -> Error:
        """
        Handle and log an error
        """
        try:
            # Generate unique error ID
            error_id = str(uuid.uuid4())
            
            # Extract error details
            error_message = str(exception)
            error_traceback = traceback.format_exc()
            
            # Determine error category and severity
            category, severity = self._classify_error(exception, error_message)
            
            # Extract context information
            context = context or {}
            module = context.get('module', 'unknown')
            function_name = context.get('function_name', '')
            
            # Extract request information
            request_data = {}
            ip_address = None
            user_agent = None
            session_id = None
            
            if request:
                request_data = {
                    'method': request.method,
                    'url': request.get_full_path(),
                    'headers': dict(request.headers),
                    'GET': dict(request.GET),
                    'POST': dict(request.POST) if hasattr(request, 'POST') else {},
                }
                ip_address = self._get_client_ip(request)
                user_agent = request.META.get('HTTP_USER_AGENT', '')
                session_id = request.session.session_key if hasattr(request, 'session') else None
            
            # Check if similar error already exists
            existing_error = self._find_similar_error(error_message, module, function_name)
            
            if existing_error:
                # Increment occurrence count
                existing_error.increment_occurrence()
                error = existing_error
            else:
                # Create new error
                error = Error.objects.create(
                    error_id=error_id,
                    title=self._generate_error_title(exception, error_message),
                    description=self._generate_error_description(exception, context),
                    category=category,
                    severity=severity,
                    module=module,
                    function_name=function_name,
                    user=user,
                    session_id=session_id,
                    error_message=error_message,
                    error_traceback=error_traceback,
                    error_data=context,
                    request_method=request.method if request else None,
                    request_url=request.get_full_path() if request else None,
                    request_data=request_data,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    tags=self._extract_tags(exception, context),
                    metadata=self._extract_metadata(exception, context)
                )
            
            # Log the error
            self._log_error(error, exception, context)
            
            # Check for auto-resolution patterns
            self._check_auto_resolution(error)
            
            return error
            
        except Exception as e:
            # Fallback logging if error handling fails
            logger.critical(f"Error in error handler: {e}")
            logger.critical(f"Original error: {exception}")
            raise
    
    def _classify_error(self, exception: Exception, error_message: str) -> tuple:
        """Classify error category and severity"""
        # Check against patterns first
        for pattern in self.patterns:
            if re.search(pattern.pattern, error_message, re.IGNORECASE):
                return pattern.category, pattern.severity
        
        # Default classification based on exception type
        exception_type = type(exception).__name__
        
        if 'ValidationError' in exception_type or 'ValueError' in exception_type:
            return ErrorCategory.VALIDATION, ErrorSeverity.MEDIUM
        elif 'PermissionDenied' in exception_type or 'AuthenticationError' in exception_type:
            return ErrorCategory.AUTHENTICATION, ErrorSeverity.HIGH
        elif 'DatabaseError' in exception_type or 'IntegrityError' in exception_type:
            return ErrorCategory.DATABASE, ErrorSeverity.HIGH
        elif 'ConnectionError' in exception_type or 'TimeoutError' in exception_type:
            return ErrorCategory.NETWORK, ErrorSeverity.MEDIUM
        elif 'BusinessLogicError' in exception_type:
            return ErrorCategory.BUSINESS_LOGIC, ErrorSeverity.MEDIUM
        elif 'SecurityError' in exception_type:
            return ErrorCategory.SECURITY, ErrorSeverity.CRITICAL
        else:
            return ErrorCategory.SYSTEM, ErrorSeverity.MEDIUM
    
    def _find_similar_error(self, error_message: str, module: str, function_name: str) -> Optional[Error]:
        """Find similar existing error"""
        try:
            # Look for errors with same message, module, and function
            return Error.objects.filter(
                error_message=error_message,
                module=module,
                function_name=function_name,
                status__in=[ErrorStatus.OPEN, ErrorStatus.IN_PROGRESS]
            ).first()
        except Exception:
            return None
    
    def _generate_error_title(self, exception: Exception, error_message: str) -> str:
        """Generate error title"""
        exception_type = type(exception).__name__
        if len(error_message) > 100:
            return f"{exception_type}: {error_message[:100]}..."
        return f"{exception_type}: {error_message}"
    
    def _generate_error_description(self, exception: Exception, context: Dict[str, Any]) -> str:
        """Generate error description"""
        description = f"An error of type {type(exception).__name__} occurred"
        
        if context.get('description'):
            description += f": {context['description']}"
        
        if context.get('user_action'):
            description += f"\nUser action: {context['user_action']}"
        
        return description
    
    def _extract_tags(self, exception: Exception, context: Dict[str, Any]) -> list:
        """Extract tags from error context"""
        tags = []
        
        # Add exception type as tag
        tags.append(type(exception).__name__)
        
        # Add module tag
        if context.get('module'):
            tags.append(f"module:{context['module']}")
        
        # Add severity tag
        if context.get('severity'):
            tags.append(f"severity:{context['severity']}")
        
        return tags
    
    def _extract_metadata(self, exception: Exception, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract metadata from error context"""
        metadata = {
            'exception_type': type(exception).__name__,
            'module': context.get('module', 'unknown'),
            'timestamp': timezone.now().isoformat(),
        }
        
        # Add any additional metadata from context
        if 'metadata' in context:
            metadata.update(context['metadata'])
        
        return metadata
    
    def _get_client_ip(self, request: HttpRequest) -> str:
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def _log_error(self, error: Error, exception: Exception, context: Dict[str, Any]):
        """Log error details"""
        try:
            ErrorLog.objects.create(
                error=error,
                level='error',
                message=f"Error occurred: {str(exception)}",
                data={
                    'exception_type': type(exception).__name__,
                    'context': context,
                    'traceback': traceback.format_exc()
                }
            )
        except Exception as e:
            logger.error(f"Failed to log error: {e}")
    
    def _check_auto_resolution(self, error: Error):
        """Check if error should be auto-resolved"""
        try:
            for pattern in self.patterns:
                if (pattern.auto_resolve and 
                    re.search(pattern.pattern, error.error_message, re.IGNORECASE)):
                    
                    # Auto-resolve the error
                    error.resolve(
                        resolved_by=None,  # System resolution
                        notes=f"Auto-resolved by pattern: {pattern.name}"
                    )
                    break
        except Exception as e:
            logger.error(f"Failed to check auto-resolution: {e}")


# Global error handler instance
error_handler = ErrorHandler()


def handle_error(exception: Exception, context: Dict[str, Any] = None, 
                request: HttpRequest = None, user: User = None) -> Error:
    """
    Convenience function to handle errors
    """
    return error_handler.handle_error(exception, context, request, user)


def log_error(error: Error, level: str, message: str, data: Dict[str, Any] = None, user: User = None):
    """
    Log additional information for an error
    """
    try:
        ErrorLog.objects.create(
            error=error,
            level=level,
            message=message,
            data=data or {},
            user=user
        )
    except Exception as e:
        logger.error(f"Failed to log error information: {e}")


def create_error_pattern(name: str, pattern: str, category: str, severity: str, 
                        module: str = None, auto_resolve: bool = False) -> ErrorPattern:
    """
    Create a new error pattern
    """
    return ErrorPattern.objects.create(
        name=name,
        pattern=pattern,
        category=category,
        severity=severity,
        module=module,
        auto_resolve=auto_resolve
    )