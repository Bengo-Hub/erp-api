"""
Core mixins for ViewSets and views.
Provides automatic branch/business context injection and validation.
"""

import logging
from rest_framework.response import Response
from rest_framework import status
from .utils import (
    get_branch_id_from_request,
    get_business_id_from_request,
    get_user_business_and_branch,
    get_business_context
)

logger = logging.getLogger(__name__)


class BusinessBranchContextMixin:
    """
    Mixin for ViewSets that automatically injects branch_id and business_id
    from request headers into serializer data when not explicitly provided.

    This ensures that even if the frontend doesn't send branch/business,
    the backend will extract them from the X-Branch-ID and X-Business-ID headers.

    Usage:
        class MyViewSet(BusinessBranchContextMixin, viewsets.ModelViewSet):
            ...

    The mixin will:
    1. Extract branch_id and business_id from headers
    2. Inject them into serializer data if not already present
    3. Add them to serializer context for access in serializer methods
    """

    # Fields to auto-inject (can be overridden in subclass)
    branch_field_name = 'branch'  # Field name in model/serializer
    business_field_name = 'business'  # Field name in model/serializer

    # Whether to require these fields (can be overridden)
    require_branch = False
    require_business = False

    def get_serializer_context(self):
        """Add branch and business context to serializer."""
        context = super().get_serializer_context()
        request = self.request

        # Get context from headers/user
        business_context = get_business_context(request)

        context['branch_id'] = business_context.get('branch_id')
        context['business_id'] = business_context.get('business_id')
        context['branch'] = business_context.get('branch')
        context['business'] = business_context.get('business')

        return context

    def _inject_context_to_data(self, data):
        """
        Inject branch_id and business_id into request data if not present.

        Args:
            data: Request data (dict)

        Returns:
            Modified data dict with branch/business injected
        """
        request = self.request

        # Get IDs from headers/user context
        business_id, branch_id = get_user_business_and_branch(request)

        # Also check explicit header values
        header_branch_id = get_branch_id_from_request(request)
        header_business_id = get_business_id_from_request(request)

        # Use header values if available, otherwise use user context
        final_branch_id = header_branch_id or branch_id
        final_business_id = header_business_id or business_id

        # Make data mutable if needed
        if hasattr(data, '_mutable'):
            data._mutable = True

        # Inject branch if not present
        if self.branch_field_name not in data or not data.get(self.branch_field_name):
            if final_branch_id:
                data[self.branch_field_name] = final_branch_id
                logger.debug(f"Auto-injected {self.branch_field_name}={final_branch_id} from context")

        # Inject business if not present
        if self.business_field_name not in data or not data.get(self.business_field_name):
            if final_business_id:
                data[self.business_field_name] = final_business_id
                logger.debug(f"Auto-injected {self.business_field_name}={final_business_id} from context")

        return data

    def _validate_required_context(self, data):
        """
        Validate that required context fields are present.
        Platform owners (superusers) bypass required context validation.

        Returns:
            tuple: (is_valid, error_response or None)
        """
        # Platform owners bypass required context
        request = self.request
        if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_superuser:
            return True, None

        errors = []

        if self.require_branch and not data.get(self.branch_field_name):
            errors.append(f'{self.branch_field_name} is required but could not be determined from request or headers')

        if self.require_business and not data.get(self.business_field_name):
            errors.append(f'{self.business_field_name} is required but could not be determined from request or headers')

        if errors:
            return False, Response(
                {'success': False, 'errors': errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        return True, None

    def create(self, request, *args, **kwargs):
        """Override create to inject branch/business context."""
        # Get mutable copy of request data
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)

        # Inject context
        data = self._inject_context_to_data(data)

        # Validate required fields
        is_valid, error_response = self._validate_required_context(data)
        if not is_valid:
            return error_response

        # Create a modified request with injected data
        request._full_data = data

        # Call parent create
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Override update to inject branch/business context if needed."""
        # Get mutable copy of request data
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)

        # Inject context (for updates, we might not need to inject if instance already has values)
        data = self._inject_context_to_data(data)

        # Create a modified request with injected data
        request._full_data = data

        return super().update(request, *args, **kwargs)

    def get_queryset(self):
        """
        Override to filter queryset by branch/business if applicable.
        Subclasses should call super() and apply additional filtering.
        """
        queryset = super().get_queryset()

        # Get context
        branch_id = get_branch_id_from_request(self.request)
        business_id = get_business_id_from_request(self.request)

        # Apply branch filter if model has branch field and branch_id is available
        if branch_id and hasattr(queryset.model, self.branch_field_name):
            queryset = queryset.filter(**{f'{self.branch_field_name}_id': branch_id})

        # Apply business filter if model has business field and business_id is available
        if business_id and hasattr(queryset.model, self.business_field_name):
            queryset = queryset.filter(**{f'{self.business_field_name}_id': business_id})

        return queryset


class RequiredBusinessContextMixin(BusinessBranchContextMixin):
    """
    Mixin that requires business context to be present.
    Returns 400 error if business cannot be determined.
    """
    require_business = True


class RequiredBranchContextMixin(BusinessBranchContextMixin):
    """
    Mixin that requires branch context to be present.
    Returns 400 error if branch cannot be determined.
    """
    require_branch = True


class RequiredFullContextMixin(BusinessBranchContextMixin):
    """
    Mixin that requires both business and branch context to be present.
    Returns 400 error if either cannot be determined.
    """
    require_business = True
    require_branch = True


class AutoBranchSerializerMixin:
    """
    Mixin for Serializers that automatically fills branch/business from context.

    Usage:
        class MySerializer(AutoBranchSerializerMixin, serializers.ModelSerializer):
            class Meta:
                model = MyModel
                fields = '__all__'
    """

    branch_field = 'branch'
    business_field = 'business'

    def validate(self, attrs):
        """Auto-fill branch and business from context if not provided."""
        attrs = super().validate(attrs)

        request = self.context.get('request')
        if not request:
            return attrs

        # Auto-fill branch
        if self.branch_field in self.fields:
            if not attrs.get(self.branch_field):
                branch_id = self.context.get('branch_id')
                if not branch_id:
                    branch_id = get_branch_id_from_request(request)
                if branch_id:
                    from business.models import Branch
                    try:
                        attrs[self.branch_field] = Branch.objects.get(id=branch_id)
                    except Branch.DoesNotExist:
                        pass

        # Auto-fill business
        if self.business_field in self.fields:
            if not attrs.get(self.business_field):
                business_id = self.context.get('business_id')
                if not business_id:
                    business_id = get_business_id_from_request(request)
                if business_id:
                    from business.models import Bussiness
                    try:
                        attrs[self.business_field] = Bussiness.objects.get(id=business_id)
                    except Bussiness.DoesNotExist:
                        pass

        return attrs
