"""
Core BaseViewSet with standardized patterns for production-ready endpoints.

This module provides base classes for implementing consistent:
- Error handling with proper status codes
- Input validation with field-level error reporting
- Audit logging for business operations
- Correlation ID tracking for request tracing
- API response standardization

Usage:
    from core.base_viewsets import BaseModelViewSet
    
    class MyViewSet(BaseModelViewSet):
        queryset = MyModel.objects.all()
        serializer_class = MySerializer
        permission_classes = [IsAuthenticated]
        
        # The ViewSet now automatically gets:
        # - Standardized error handling
        # - APIResponse wrapper
        # - Audit logging
        # - Correlation ID tracking
"""

from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.core.exceptions import ValidationError
import logging

from .response import APIResponse, get_correlation_id
from .audit import AuditTrail
from .validators import validate_non_negative_decimal

logger = logging.getLogger(__name__)


class BaseModelViewSet(viewsets.ModelViewSet):
    """
    Enhanced ModelViewSet with standardized error handling, validation, and audit logging.
    
    Provides consistent patterns across all endpoints:
    - APIResponse wrapper for all responses
    - Correlation ID tracking
    - Audit logging for CREATE/UPDATE/DELETE operations
    - Transaction management for data consistency
    - Field-level error reporting
    - Automatic error code generation
    """
    
    permission_classes = [IsAuthenticated]
    
    def get_correlation_id(self):
        """Extract correlation ID from request headers or generate new one."""
        return get_correlation_id(self.request)
    
    def get_user(self):
        """Get authenticated user from request."""
        return self.request.user if self.request.user.is_authenticated else None
    
    def get_module_name(self):
        """Get module name from app config or ViewSet name."""
        app_name = self.__class__.__module__.split('.')[0]
        return app_name or 'unknown'
    
    def get_entity_type(self):
        """Get entity type from model name."""
        if hasattr(self, 'queryset') and self.queryset.model:
            return self.queryset.model.__name__
        return self.__class__.__name__.replace('ViewSet', '')
    
    def get_entity_id(self, obj):
        """Get entity ID from object."""
        return getattr(obj, 'pk', None) or getattr(obj, 'id', None)
    
    def log_operation(self, operation, obj, changes=None, reason=None):
        """Log operation to audit trail."""
        try:
            AuditTrail.log(
                operation=operation,
                module=self.get_module_name(),
                entity_type=self.get_entity_type(),
                entity_id=self.get_entity_id(obj),
                user=self.get_user(),
                changes=changes or {},
                reason=reason or f'{operation} operation on {self.get_entity_type()}',
                request=self.request
            )
        except Exception as e:
            logger.error(f'Error logging audit trail: {str(e)}')
    
    def list(self, request, *args, **kwargs):
        """List with standardized error handling."""
        try:
            correlation_id = self.get_correlation_id()
            
            # Get filtered queryset
            queryset = self.filter_queryset(self.get_queryset())
            
            # Apply pagination
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                response_data = self.get_paginated_response(serializer.data)
                # Wrap paginated response
                if isinstance(response_data.data, dict):
                    response_data.data['correlation_id'] = correlation_id
                return response_data
            
            # No pagination
            serializer = self.get_serializer(queryset, many=True)
            return APIResponse.success(
                data=serializer.data,
                message=f'{self.get_entity_type()} list retrieved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error listing {self.get_entity_type()}: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            return APIResponse.server_error(
                message=f'Error retrieving {self.get_entity_type()} list',
                error_id=str(e),
                correlation_id=correlation_id
            )
    
    def retrieve(self, request, *args, **kwargs):
        """Retrieve with standardized error handling."""
        try:
            correlation_id = self.get_correlation_id()
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            
            return APIResponse.success(
                data=serializer.data,
                message=f'{self.get_entity_type()} retrieved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error retrieving {self.get_entity_type()}: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            
            if '404' in str(e) or 'not found' in str(e).lower():
                return APIResponse.not_found(
                    message=f'{self.get_entity_type()} not found',
                    correlation_id=correlation_id
                )
            
            return APIResponse.server_error(
                message=f'Error retrieving {self.get_entity_type()}',
                error_id=str(e),
                correlation_id=correlation_id
            )
    
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """Create with validation, transaction management, and audit logging."""
        try:
            correlation_id = self.get_correlation_id()
            serializer = self.get_serializer(data=request.data)
            
            if not serializer.is_valid():
                return APIResponse.validation_error(
                    message='Validation failed',
                    errors=serializer.errors,
                    correlation_id=correlation_id
                )
            
            # Save the instance
            instance = serializer.save()
            
            # Log creation
            self.log_operation(
                operation=AuditTrail.CREATE,
                obj=instance,
                reason=f'Created new {self.get_entity_type()}'
            )
            
            return APIResponse.created(
                data=self.get_serializer(instance).data,
                message=f'{self.get_entity_type()} created successfully',
                correlation_id=correlation_id
            )
        except ValidationError as e:
            logger.error(f'Validation error creating {self.get_entity_type()}: {str(e)}')
            correlation_id = self.get_correlation_id()
            return APIResponse.validation_error(
                message='Validation failed',
                errors={'detail': str(e)},
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error creating {self.get_entity_type()}: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            return APIResponse.server_error(
                message=f'Error creating {self.get_entity_type()}',
                error_id=str(e),
                correlation_id=correlation_id
            )
    
    @transaction.atomic
    def update(self, request, *args, **kwargs):
        """Update with validation, transaction management, and audit logging."""
        try:
            correlation_id = self.get_correlation_id()
            partial = kwargs.pop('partial', False)
            instance = self.get_object()
            
            # Track changes for audit log
            old_data = self.get_serializer(instance).data
            
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            
            if not serializer.is_valid():
                return APIResponse.validation_error(
                    message='Validation failed',
                    errors=serializer.errors,
                    correlation_id=correlation_id
                )
            
            # Save the instance
            updated_instance = serializer.save()
            new_data = self.get_serializer(updated_instance).data
            
            # Calculate changes
            changes = {key: {'old': old_data.get(key), 'new': new_data.get(key)} 
                      for key in new_data if old_data.get(key) != new_data.get(key)}
            
            # Log update
            self.log_operation(
                operation=AuditTrail.UPDATE,
                obj=updated_instance,
                changes=changes,
                reason=f'Updated {self.get_entity_type()}'
            )
            
            return APIResponse.success(
                data=new_data,
                message=f'{self.get_entity_type()} updated successfully',
                correlation_id=correlation_id
            )
        except ValidationError as e:
            logger.error(f'Validation error updating {self.get_entity_type()}: {str(e)}')
            correlation_id = self.get_correlation_id()
            return APIResponse.validation_error(
                message='Validation failed',
                errors={'detail': str(e)},
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error updating {self.get_entity_type()}: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            
            if '404' in str(e) or 'not found' in str(e).lower():
                return APIResponse.not_found(
                    message=f'{self.get_entity_type()} not found',
                    correlation_id=correlation_id
                )
            
            return APIResponse.server_error(
                message=f'Error updating {self.get_entity_type()}',
                error_id=str(e),
                correlation_id=correlation_id
            )
    
    def partial_update(self, request, *args, **kwargs):
        """Partial update (PATCH) with same error handling as update."""
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)
    
    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """Delete with audit logging and transaction management."""
        try:
            correlation_id = self.get_correlation_id()
            instance = self.get_object()
            entity_id = self.get_entity_id(instance)
            entity_type = self.get_entity_type()
            
            # Log deletion before deleting
            self.log_operation(
                operation=AuditTrail.DELETE,
                obj=instance,
                reason=f'Deleted {entity_type}'
            )
            
            # Delete the instance
            self.perform_destroy(instance)
            
            return APIResponse.success(
                data={'id': entity_id, 'deleted': True},
                message=f'{entity_type} deleted successfully',
                status_code=status.HTTP_204_NO_CONTENT,
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error deleting {self.get_entity_type()}: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            
            if '404' in str(e) or 'not found' in str(e).lower():
                return APIResponse.not_found(
                    message=f'{self.get_entity_type()} not found',
                    correlation_id=correlation_id
                )
            
            return APIResponse.server_error(
                message=f'Error deleting {self.get_entity_type()}',
                error_id=str(e),
                correlation_id=correlation_id
            )


class BaseReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Enhanced ReadOnlyModelViewSet with standardized error handling and response formatting.
    
    Use this for endpoints that only support list and retrieve operations.
    """
    
    permission_classes = [IsAuthenticated]
    
    def get_correlation_id(self):
        """Extract correlation ID from request headers or generate new one."""
        return get_correlation_id(self.request)
    
    def get_module_name(self):
        """Get module name from app config or ViewSet name."""
        app_name = self.__class__.__module__.split('.')[0]
        return app_name or 'unknown'
    
    def get_entity_type(self):
        """Get entity type from model name."""
        if hasattr(self, 'queryset') and self.queryset.model:
            return self.queryset.model.__name__
        return self.__class__.__name__.replace('ViewSet', '')
    
    def list(self, request, *args, **kwargs):
        """List with standardized error handling."""
        try:
            correlation_id = self.get_correlation_id()
            
            queryset = self.filter_queryset(self.get_queryset())
            
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                response_data = self.get_paginated_response(serializer.data)
                if isinstance(response_data.data, dict):
                    response_data.data['correlation_id'] = correlation_id
                return response_data
            
            serializer = self.get_serializer(queryset, many=True)
            return APIResponse.success(
                data=serializer.data,
                message=f'{self.get_entity_type()} list retrieved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error listing {self.get_entity_type()}: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            return APIResponse.server_error(
                message=f'Error retrieving {self.get_entity_type()} list',
                error_id=str(e),
                correlation_id=correlation_id
            )
    
    def retrieve(self, request, *args, **kwargs):
        """Retrieve with standardized error handling."""
        try:
            correlation_id = self.get_correlation_id()
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            
            return APIResponse.success(
                data=serializer.data,
                message=f'{self.get_entity_type()} retrieved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error retrieving {self.get_entity_type()}: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            
            if '404' in str(e) or 'not found' in str(e).lower():
                return APIResponse.not_found(
                    message=f'{self.get_entity_type()} not found',
                    correlation_id=correlation_id
                )
            
            return APIResponse.server_error(
                message=f'Error retrieving {self.get_entity_type()}',
                error_id=str(e),
                correlation_id=correlation_id
            )
