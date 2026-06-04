"""
Custom permissions and mixins for HRM module.
Implements row-level security for staff users.
"""
from rest_framework import permissions
from django.db.models import Q

# Group names treated as HR / managerial roles for approval-style actions.
# These mirror the groups provisioned by authmanagement (see
# authmanagement/management/commands and sso.py group sync). Names are matched
# case-insensitively. Assumption (documented per feedback rules): the RBAC model
# in this codebase is Django Groups + model permissions; there is no dedicated
# "manager" boolean on Employee, so HR/manager authority is expressed via
# membership in one of these groups, the is_staff flag, or holding the relevant
# change_<model> permission.
HR_MANAGER_GROUP_NAMES = (
    'hr',
    'hr_manager',
    'human_resources',
    'manager',
    'admin',
    'superusers',
)


def is_hr_or_manager(user, view=None):
    """Return True if ``user`` should be allowed to perform HR/manager-only
    write/approval actions.

    Authority is granted if the user is a superuser, is Django staff, belongs to
    one of :data:`HR_MANAGER_GROUP_NAMES`, or holds the ``change_<model>``
    permission for the view's model (when a model can be resolved). This is
    intentionally permissive on reads (handled by the calling permission class)
    and conservative on writes, and never locks anyone out of safe methods.
    """
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser or user.is_staff:
        return True
    if user.groups.filter(name__in=HR_MANAGER_GROUP_NAMES).exists():
        return True
    # Also honour an explicit model change permission, mirroring IsOwnerOrElevated.
    model = _resolve_model(view)
    if model is not None:
        model_name = model.__name__.lower()
        app_label = model._meta.app_label
        if user.has_perm(f'{app_label}.change_{model_name}') or \
           user.has_perm(f'{app_label}.delete_{model_name}'):
            return True
    return False


def _resolve_model(view):
    """Best-effort resolution of the model behind a viewset/view."""
    if view is None:
        return None
    queryset = getattr(view, 'queryset', None)
    if queryset is not None:
        return queryset.model
    return None


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


class ReadOnlyOrHR(permissions.BasePermission):
    """
    Allow safe (read-only) methods to any authenticated user, but restrict
    unsafe methods (POST/PUT/PATCH/DELETE) and HR/manager-only actions to users
    who pass :func:`is_hr_or_manager`.

    Intended for viewsets where listing/retrieving should stay open to all
    authenticated users while writes are gated. Does not lock anyone out of read.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return is_hr_or_manager(request.user, view)


class IsHRorManager(permissions.BasePermission):
    """
    Allow access only to HR/manager users (see :func:`is_hr_or_manager`).

    Designed to be attached to specific approval/sensitive ``@action`` methods
    (e.g. approve/reject) via ``self.check_permissions`` or per-action
    ``get_permissions``. When used as a viewset-wide permission it would also
    gate reads, so prefer :class:`ReadOnlyOrHR` for whole viewsets and use this
    only to guard individual write/approval actions.
    """

    def has_permission(self, request, view):
        return is_hr_or_manager(request.user, view)

    def has_object_permission(self, request, view, obj):
        return is_hr_or_manager(request.user, view)

