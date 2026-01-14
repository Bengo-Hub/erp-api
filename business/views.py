from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters
from rest_framework.pagination import LimitOffsetPagination
from .models import (BusinessLocation, Bussiness, ProductSettings, SaleSettings,
                     PrefixSettings, ServiceTypes, PickupStations,
                     BrandingSettings, Branch, DocumentSequence)
from addresses.models import AddressBook
from .serializers import *
from addresses.models import DeliveryRegion
from core.decorators import apply_common_filters


def get_user_business(user):
    """
    Helper function to get the business associated with a user.
    Returns the business if user is owner or employee, None otherwise.
    """
    # Check if user owns a business
    business = Bussiness.objects.filter(owner=user).first()
    if business:
        return business

    # Check if user is an employee
    from hrm.employees.models import Employee
    employee = Employee.objects.filter(user=user).select_related('organisation').first()
    if employee and employee.organisation:
        return employee.organisation

    return None


class BusinessLocationViewSet(viewsets.ModelViewSet):
    queryset = BusinessLocation.objects.all()
    serializer_class = BusinessLocationSerializer
    permission_classes=[IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        business_name = self.request.query_params.get('business_name')
        if business_name:
            # Filter through branches to get business locations
            queryset = queryset.filter(branches__business__name=business_name)
        return queryset


class BussinessViewSet(viewsets.ModelViewSet):
    """
    Business settings viewset - uses lean serializer by default.
    Endpoint: /api/v1/business/settings/

    Actions:
    - list: GET /api/v1/business/settings/ - returns user's business (lean)
    - retrieve: GET /api/v1/business/settings/{id}/ - returns business by id (lean)
    - update/partial_update: PATCH /api/v1/business/settings/{id}/ - update business
    - full: GET /api/v1/business/settings/{id}/full/ - returns full business with all relations
    """
    queryset = Bussiness.objects.all()
    serializer_class = BusinessSettingsSerializer  # Lean serializer by default
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter to user's business - always returns only the user's own business."""
        user = self.request.user
        business = get_user_business(user)
        if business:
            return Bussiness.objects.filter(id=business.id)
        return Bussiness.objects.none()

    def get_serializer_class(self):
        """Use full serializer only for 'full' action."""
        if self.action == 'full':
            return BussinessSerializer
        return BusinessSettingsSerializer

    @action(detail=True, methods=['get'], url_path='full')
    def full(self, request, pk=None):
        """Get full business data with all relations (branches, tax rates, etc.)"""
        business = self.get_object()
        serializer = BussinessSerializer(business)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def branding(self, request, pk=None):
        """Get detailed branding settings for a business"""
        business = self.get_object()
        branding_data = business.get_branding_settings()
        return Response(branding_data)

    @action(detail=True, methods=['get'], url_path='branches')
    def get_branches_for_business(self, request, pk=None):
        """Return branches for this business (convenience endpoint for frontend)"""
        business = self.get_object()
        branches = Branch.objects.filter(business=business, is_active=True)
        serializer = BranchSerializer(branches, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='branches')
    def create_branch_for_business(self, request, pk=None):
        """Create a new branch for this business (sets business automatically)."""
        business = self.get_object()
        data = request.data.copy()
        data['business'] = business.id
        serializer = BranchSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        branch = serializer.save()
        return Response(BranchSerializer(branch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='branding/update')
    def update_branding(self, request, pk=None):
        """Update branding settings for a business"""
        business = self.get_object()
        data = request.data

        # Update business branding fields
        if 'primary_color' in data:
            business.business_primary_color = data['primary_color']
        if 'secondary_color' in data:
            business.business_secondary_color = data['secondary_color']
        if 'text_color' in data:
            business.business_text_color = data['text_color']
        if 'background_color' in data:
            business.business_background_color = data['background_color']
        if 'theme_preset' in data:
            business.ui_theme_preset = data['theme_preset']
        if 'menu_mode' in data:
            business.ui_menu_mode = data['menu_mode']
        if 'dark_mode' in data:
            business.ui_dark_mode = data['dark_mode']
        if 'surface_style' in data:
            business.ui_surface_style = data['surface_style']

        # Save business model
        business.save()

        # Update extended branding settings
        try:
            branding, created = BrandingSettings.objects.get_or_create(business=business)

            if 'primary_color_name' in data:
                branding.primary_color_name = data['primary_color_name']
            if 'surface_name' in data:
                branding.surface_name = data['surface_name']

            # Check for extended settings
            extended = data.get('extended_settings', {})
            if extended:
                if 'compact_mode' in extended:
                    branding.compact_mode = extended['compact_mode']
                if 'ripple_effect' in extended:
                    branding.ripple_effect = extended['ripple_effect']
                if 'border_radius' in extended:
                    branding.border_radius = extended['border_radius']
                if 'scale_factor' in extended:
                    branding.scale_factor = extended['scale_factor']

            # Save branding model
            branding.save()

            # Return updated branding settings
            return Response(business.get_branding_settings())
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def compliance(self, request, pk=None):
        """Return basic business compliance status (KRA PIN presence, license expiry)."""
        business = self.get_object()
        status_data = {
            'kra_pin_present': bool(getattr(business, 'kra_number', None)),
            'license_number_present': bool(getattr(business, 'business_license_number', None)),
            'license_expired': False,
        }
        try:
            from datetime import date
            exp = getattr(business, 'business_license_expiry', None)
            if exp:
                status_data['license_expired'] = date.today() > exp
        except Exception:
            pass
        return Response(status_data)

class BranchesViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter branches to user's business."""
        user = self.request.user
        if user.is_superuser:
            return Branch.objects.all()

        business = get_user_business(user)
        if business:
            return Branch.objects.filter(business=business, is_active=True)
        return Branch.objects.none()

    def perform_create(self, serializer):
        """Auto-assign business when creating a branch."""
        if 'business' not in serializer.validated_data:
            business = get_user_business(self.request.user)
            if business:
                serializer.save(business=business)
                return
        serializer.save()

class ProductSettingsViewSet(viewsets.ModelViewSet):
    queryset = ProductSettings.objects.all()
    serializer_class = ProductSettingsSerializer
    permission_classes=[IsAuthenticated]

class SaleSettingsViewSet(viewsets.ModelViewSet):
    queryset = SaleSettings.objects.all()
    serializer_class = SaleSettingsSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter sale settings to user's business."""
        user = self.request.user
        if user.is_superuser:
            return SaleSettings.objects.all()

        business = get_user_business(user)
        if business:
            return SaleSettings.objects.filter(business=business)
        return SaleSettings.objects.none()

    def perform_create(self, serializer):
        """Auto-assign business when creating sale settings."""
        if 'business' not in serializer.validated_data:
            business = get_user_business(self.request.user)
            if business:
                serializer.save(business=business)
                return
        serializer.save()

class PrefixSettingsViewSet(viewsets.ModelViewSet):
    queryset = PrefixSettings.objects.all()
    serializer_class = PrefixSettingsSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter prefix settings to user's business."""
        user = self.request.user
        if user.is_superuser:
            return PrefixSettings.objects.all()

        business = get_user_business(user)
        if business:
            return PrefixSettings.objects.filter(business=business)
        return PrefixSettings.objects.none()

    def perform_create(self, serializer):
        """Auto-assign business when creating prefix settings."""
        if 'business' not in serializer.validated_data:
            business = get_user_business(self.request.user)
            if business:
                serializer.save(business=business)
                return
        serializer.save()

class ServiceTypesViewSet(viewsets.ModelViewSet):
    queryset = ServiceTypes.objects.all()
    serializer_class = ServiceTypesSerializer
    permission_classes=[IsAuthenticated]

class DeliveryRegionsViewSet(viewsets.ModelViewSet):
    queryset = DeliveryRegion.objects.all()
    serializer_class = DeliveryAddressSerializer
    permission_classes=[IsAuthenticated]

    def get_queryset(self):
        queryset = self.queryset

        # Filter by regions that have active pickup stations if requested
        with_pickup_stations = self.request.query_params.get('with_pickup_stations', None)
        if with_pickup_stations:
            # Get regions that have at least one active pickup station
            regions_with_stations = PickupStations.objects.filter(is_active=True).values_list('region', flat=True).distinct()
            queryset = queryset.filter(id__in=regions_with_stations)

        return queryset

    @action(detail=False, methods=['get'], url_path='with-pickup-stations', url_name='with-pickup-stations')
    def with_pickup_stations(self, request):
        """Get only regions that have pickup stations"""
        regions_with_stations = PickupStations.objects.filter(is_active=True).values_list('region', flat=True).distinct()
        queryset = DeliveryRegion.objects.filter(id__in=regions_with_stations)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class PickupStationsViewSet(viewsets.ModelViewSet):
    queryset = PickupStations.objects.all()
    serializer_class = PickupStationsSerializer
    permission_classes=[IsAuthenticated]

    def get_queryset(self):
        queryset = self.queryset

        # Filter by region if provided
        region = self.request.query_params.get('region', None)
        if region:
            queryset = queryset.filter(region__id=region)

        # Filter by active status
        queryset = queryset.filter(is_active=True)

        # Order by priority
        queryset = queryset.order_by('-priority_order', 'pickup_location')

        return queryset

# AddressBookViewSet moved to addresses app - import from there
# from addresses.views import AddressBookViewSet


class DocumentSequenceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and managing document sequences.
    Allows GET for viewing, PATCH for updating, and POST for custom actions.
    """
    queryset = DocumentSequence.objects.all()
    serializer_class = DocumentSequenceSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        """Filter document sequences to user's business."""
        user = self.request.user
        if user.is_superuser:
            return DocumentSequence.objects.all()

        business = get_user_business(user)
        if business:
            return DocumentSequence.objects.filter(business=business)
        return DocumentSequence.objects.none()

    @action(detail=False, methods=['post'], url_path='update-sequence')
    def update_sequence(self, request):
        """
        Update or create a document sequence for a specific document type.
        Useful for setting initial sequence values or resetting sequences.
        """
        from .document_service import DocumentNumberService

        document_type = request.data.get('document_type')
        current_sequence = request.data.get('current_sequence')

        if not document_type:
            return Response({'error': 'document_type is required'}, status=status.HTTP_400_BAD_REQUEST)

        if current_sequence is None:
            return Response({'error': 'current_sequence is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            current_sequence = int(current_sequence)
            if current_sequence < 0:
                return Response({'error': 'current_sequence cannot be negative'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'error': 'current_sequence must be a valid integer'}, status=status.HTTP_400_BAD_REQUEST)

        business = get_user_business(request.user)
        if not business:
            return Response({'error': 'No business found'}, status=status.HTTP_404_NOT_FOUND)

        # Validate document type
        valid_types = [choice[0] for choice in DocumentSequence.DOCUMENT_TYPE_CHOICES]
        if document_type not in valid_types:
            return Response({'error': f'Invalid document_type. Must be one of: {valid_types}'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            sequence = DocumentNumberService.set_sequence(business, document_type, current_sequence)
            preview = DocumentNumberService.get_next_sequence_preview(business, document_type)
            return Response({
                'message': f'Sequence updated successfully',
                'document_type': document_type,
                'document_type_display': sequence.get_document_type_display(),
                'current_sequence': sequence.current_sequence,
                'next_number': preview['next_number'],
                'prefix': preview['prefix']
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        """
        Get a summary of all document sequences with their current values and next numbers.
        """
        from .document_service import DocumentNumberService

        business = get_user_business(request.user)
        if not business:
            return Response({'error': 'No business found'}, status=status.HTTP_404_NOT_FOUND)

        sequences = DocumentSequence.objects.filter(business=business)
        summary = []

        for seq in sequences:
            preview = DocumentNumberService.get_next_sequence_preview(business, seq.document_type)
            summary.append({
                'document_type': seq.document_type,
                'document_type_display': seq.get_document_type_display(),
                'current_sequence': seq.current_sequence,
                'next_number': preview['next_number'],
                'prefix': preview['prefix'],
            })

        # Add document types that don't have sequences yet
        existing_types = set(s.document_type for s in sequences)
        for doc_type, display in DocumentSequence.DOCUMENT_TYPE_CHOICES:
            if doc_type not in existing_types:
                preview = DocumentNumberService.get_next_sequence_preview(business, doc_type)
                summary.append({
                    'document_type': doc_type,
                    'document_type_display': display,
                    'current_sequence': 0,
                    'next_number': preview['next_number'],
                    'prefix': preview['prefix'],
                })

        return Response(summary)
