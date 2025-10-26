"""
Custom permissions and mixins for HRM module.
Implements row-level security for staff users.
"""
from rest_framework import permissions
from django.db.models import Q


class IsOwnerOrElevated(permissions.BasePermission):
    """
    Permission that allows users to access their own records,
    or all records if they have elevated permissions (change/delete).
    """
    
    def has_permission(self, request, view):
        # All authenticated users can access the endpoint
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # Superusers can access everything
        if request.user.is_superuser:
            return True
        
        # Users with change or delete permissions can access all records
        model_name = obj.__class__.__name__.lower()
        app_label = obj._meta.app_label
        
        has_change = request.user.has_perm(f'{app_label}.change_{model_name}')
        has_delete = request.user.has_perm(f'{app_label}.delete_{model_name}')
        
        if has_change or has_delete:
            return True
        
        # Check if user is the owner (has associated employee record)
        try:
            employee = request.user.employee
            
            # Check if object has employee field
            if hasattr(obj, 'employee'):
                return obj.employee == employee
            
            # Check if object has user field
            if hasattr(obj, 'user'):
                return obj.user == request.user
                
        except AttributeError:
            pass
        
        # Deny by default
        return False


class CanViewSensitiveModule(permissions.BasePermission):
    """
    Permission that checks if user can access sensitive modules.
    User must have change/delete permissions or be assigned as approver.
    """
    
    def has_permission(self, request, view):
        # Superusers always have access
        if request.user.is_superuser:
            return True
        
        # Get model info from view
        if not hasattr(view, 'queryset') or view.queryset is None:
            return True  # Allow if no queryset defined
        
        model = view.queryset.model
        model_name = model.__name__.lower()
        app_label = model._meta.app_label
        
        # Check for elevated permissions
        has_change = request.user.has_perm(f'{app_label}.change_{model_name}')
        has_delete = request.user.has_perm(f'{app_label}.delete_{model_name}')
        has_add = request.user.has_perm(f'{app_label}.add_{model_name}')
        
        # If user has change or delete permission, grant access
        if has_change or has_delete:
            return True
        
        # Check if user is assigned as approver
        try:
            employee = request.user.employee
            
            # Check various approver fields
            approver_fields = ['approver', 'approved_by', 'reviewer', 'line_manager']
            for field in approver_fields:
                if hasattr(model, field):
                    return True  # Will be filtered in queryset
                    
        except AttributeError:
            pass
        
        # For staff with only 'add' and 'view' permissions, allow access to their own records
        if has_add:
            return True
        
        # Deny by default for sensitive modules
        return False


class StaffDataFilterMixin:
    """
    Mixin to filter queryset based on user permissions.
    Staff users only see their own records unless they have elevated permissions.
    """
    
    # Fields to check for ownership (in order of priority)
    ownership_fields = ['employee', 'user', 'created_by']
    
    # Fields to check for approver assignment
    approver_fields = ['approver', 'approved_by', 'reviewer', 'line_manager', 'manager']
    
    def get_queryset(self):
        """
        Filter queryset based on user permissions and ownership.
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        # Superusers see everything
        if user.is_superuser:
            return queryset
        
        # Get model info
        model = queryset.model
        model_name = model.__name__.lower()
        app_label = model._meta.app_label
        
        # Check for elevated permissions
        has_change = user.has_perm(f'{app_label}.change_{model_name}')
        has_delete = user.has_perm(f'{app_label}.delete_{model_name}')
        
        # Users with change or delete permissions see all records
        if has_change or has_delete:
            return queryset
        
        # Try to get employee record
        try:
            employee = user.employee
        except AttributeError:
            # User has no employee record, return empty queryset
            return queryset.none()
        
        # Build filter for owned records
        q_filter = Q()
        
        # Check ownership fields
        for field in self.ownership_fields:
            if hasattr(model, field):
                if field == 'employee':
                    q_filter |= Q(**{field: employee})
                elif field == 'user':
                    q_filter |= Q(**{field: user})
                elif field == 'created_by':
                    q_filter |= Q(**{field: user})
        
        # Check approver fields (user is assigned as approver)
        for field in self.approver_fields:
            if hasattr(model, field):
                q_filter |= Q(**{field: employee}) | Q(**{f'{field}__user': user})
        
        # Apply filter
        if q_filter:
            return queryset.filter(q_filter).distinct()
        
        # No matching fields found, return empty queryset for safety
        return queryset.none()
    
    def perform_create(self, serializer):
        """
        Automatically set ownership fields on creation.
        """
        kwargs = {}
        
        # Try to set employee field
        try:
            employee = self.request.user.employee
            if hasattr(serializer.Meta.model, 'employee'):
                kwargs['employee'] = employee
        except AttributeError:
            pass
        
        # Set user field if available
        if hasattr(serializer.Meta.model, 'user'):
            kwargs['user'] = self.request.user
        
        # Set created_by field if available
        if hasattr(serializer.Meta.model, 'created_by'):
            kwargs['created_by'] = self.request.user
        
        serializer.save(**kwargs)


class SensitiveModuleFilterMixin(StaffDataFilterMixin):
    """
    Enhanced mixin for sensitive modules with stricter access controls.
    """
    permission_classes = [permissions.IsAuthenticated, CanViewSensitiveModule]

