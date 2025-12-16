"""
Standardized API Response Wrapper

Provides consistent response formatting across all API endpoints with:
- Success/error status
- Correlation IDs for request tracking
- Timestamps
- Consistent error codes and messages
"""

import uuid
from typing import Any, Dict, Optional, List
from rest_framework import status
from rest_framework.response import Response
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class APIResponse:
    """
    Standardized API response wrapper for consistent response formatting.
    
    Provides methods for success and error responses with automatic correlation IDs,
    timestamps, and proper HTTP status codes.
    """
    
    @staticmethod
    def success(
        data: Any = None,
        message: str = "Success",
        status_code: int = status.HTTP_200_OK,
        correlation_id: Optional[str] = None,
        **kwargs
    ) -> Response:
        """
        Generate a success response.
        
        Args:
            data: Response data (can be dict, list, or any serializable object)
            message: Success message
            status_code: HTTP status code (default: 200)
            correlation_id: Optional request correlation ID for tracking
            **kwargs: Additional fields to include in response
        
        Returns:
            Response: DRF Response object
        
        Example:
            return APIResponse.success(
                data={'id': 1, 'name': 'John'},
                message='User retrieved successfully'
            )
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        response_data = {
            'success': True,
            'message': message,
            'data': data,
            'timestamp': timezone.now().isoformat(),
            'correlation_id': correlation_id,
        }
        
        # Add any additional fields
        response_data.update(kwargs)
        
        return Response(response_data, status=status_code)
    
    @staticmethod
    def error(
        error_code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[Dict[str, Any]] = None,
        errors: Optional[List[Dict[str, str]]] = None,
        correlation_id: Optional[str] = None,
        **kwargs
    ) -> Response:
        """
        Generate an error response.
        
        Args:
            error_code: Unique error code (e.g., 'INVALID_INPUT', 'RESOURCE_NOT_FOUND')
            message: Human-readable error message
            status_code: HTTP status code (default: 400)
            details: Additional error details
            errors: List of validation errors with field-level details
            correlation_id: Optional request correlation ID for tracking
            **kwargs: Additional fields to include in response
        
        Returns:
            Response: DRF Response object
        
        Example:
            return APIResponse.error(
                error_code='INVALID_EMAIL',
                message='Email format is invalid',
                status_code=status.HTTP_400_BAD_REQUEST,
                details={'field': 'email', 'value': 'invalid-email'}
            )
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        response_data = {
            'success': False,
            'error': {
                'code': error_code,
                'message': message,
            },
            'timestamp': timezone.now().isoformat(),
            'correlation_id': correlation_id,
        }
        
        if details:
            response_data['error']['details'] = details
        
        if errors:
            response_data['errors'] = errors
        
        # Add any additional fields
        response_data.update(kwargs)
        
        return Response(response_data, status=status_code)
    
    @staticmethod
    def created(
        data: Dict[str, Any],
        message: str = "Resource created successfully",
        correlation_id: Optional[str] = None
    ) -> Response:
        """
        Generate a 201 Created response.
        
        Args:
            data: Created resource data
            message: Success message
            correlation_id: Optional request correlation ID
        
        Returns:
            Response: DRF Response object with 201 status
        """
        return APIResponse.success(
            data=data,
            message=message,
            status_code=status.HTTP_201_CREATED,
            correlation_id=correlation_id
        )
    
    @staticmethod
    def validation_error(
        message: str = "Validation failed",
        errors: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> Response:
        """
        Generate a validation error response (400).
        
        Args:
            message: Error message
            errors: Dictionary of validation errors {field: error_message}
            correlation_id: Optional request correlation ID
        
        Returns:
            Response: DRF Response object
        
        Example:
            return APIResponse.validation_error(
                message='Input validation failed',
                errors={'email': 'Invalid email format', 'age': 'Must be 18+'}
            )
        """
        errors_list = [
            {'field': field, 'message': str(error)}
            for field, error in (errors or {}).items()
        ]
        
        return APIResponse.error(
            error_code='VALIDATION_ERROR',
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            errors=errors_list,
            correlation_id=correlation_id
        )

    @staticmethod
    def bad_request(
        message: str = "Bad request",
        errors: Optional[Dict[str, Any]] = None,
        error_id: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> Response:
        """
        Convenience wrapper for 400 Bad Request responses.

        Keeps backward compatibility with code that used APIResponse.bad_request.
        """
        details = None
        if error_id:
            details = {'error_id': error_id}

        return APIResponse.error(
            error_code='BAD_REQUEST',
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
            errors=[{'field': k, 'message': str(v)} for k, v in (errors or {}).items()] if isinstance(errors, dict) else errors,
            correlation_id=correlation_id
        )
    
    @staticmethod
    def not_found(
        message: str = "Resource not found",
        correlation_id: Optional[str] = None
    ) -> Response:
        """
        Generate a 404 Not Found response.
        
        Args:
            message: Error message
            correlation_id: Optional request correlation ID
        
        Returns:
            Response: DRF Response object
        """
        return APIResponse.error(
            error_code='RESOURCE_NOT_FOUND',
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            correlation_id=correlation_id
        )
    
    @staticmethod
    def unauthorized(
        message: str = "Authentication required",
        correlation_id: Optional[str] = None
    ) -> Response:
        """
        Generate a 401 Unauthorized response.
        
        Args:
            message: Error message
            correlation_id: Optional request correlation ID
        
        Returns:
            Response: DRF Response object
        """
        return APIResponse.error(
            error_code='UNAUTHORIZED',
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            correlation_id=correlation_id
        )
    
    @staticmethod
    def forbidden(
        message: str = "You do not have permission to access this resource",
        correlation_id: Optional[str] = None
    ) -> Response:
        """
        Generate a 403 Forbidden response.
        
        Args:
            message: Error message
            correlation_id: Optional request correlation ID
        
        Returns:
            Response: DRF Response object
        """
        return APIResponse.error(
            error_code='FORBIDDEN',
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            correlation_id=correlation_id
        )
    
    @staticmethod
    def server_error(
        message: str = "Internal server error",
        error_id: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> Response:
        """
        Generate a 500 Internal Server Error response.
        
        Args:
            message: Error message
            error_id: Optional unique error ID for tracking
            correlation_id: Optional request correlation ID
        
        Returns:
            Response: DRF Response object
        """
        error_id = error_id or str(uuid.uuid4())
        
        return APIResponse.error(
            error_code='INTERNAL_SERVER_ERROR',
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={'error_id': error_id},
            correlation_id=correlation_id
        )


# Convenience function for extracting/generating correlation IDs from requests
def get_correlation_id(request) -> str:
    """
    Extract or generate a correlation ID for request tracking.
    
    Args:
        request: Django request object
    
    Returns:
        str: Correlation ID (from header or newly generated)
    """
    # Check if correlation ID provided in request headers
    correlation_id = request.META.get('HTTP_X_CORRELATION_ID')
    if correlation_id:
        return correlation_id
    
    # Generate new correlation ID
    return str(uuid.uuid4())
