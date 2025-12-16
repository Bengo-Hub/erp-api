from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters
from rest_framework.pagination import LimitOffsetPagination
from .models import (BusinessLocation, Bussiness, ProductSettings, SaleSettings,
                     PrefixSettings, ServiceTypes, PickupStations,
                     BrandingSettings, TaxRates, Branch)
from addresses.models import AddressBook
from .serializers import *
from addresses.models import DeliveryRegion
from core.decorators import apply_common_filters


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
    queryset = Bussiness.objects.all().prefetch_related('branches__location', 'branding')
    serializer_class = BussinessSerializer
    permission_classes=[IsAuthenticated]

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
    permission_classes=[IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        business_name = self.request.query_params.get('business_name')
        if business_name:
            queryset = queryset.filter(business__name=business_name)
        return queryset

class TaxRatesViewSet(viewsets.ModelViewSet):
    queryset = TaxRates.objects.all()
    serializer_class = TaxRatesSerializer
    permission_classes=[IsAuthenticated]

class ProductSettingsViewSet(viewsets.ModelViewSet):
    queryset = ProductSettings.objects.all()
    serializer_class = ProductSettingsSerializer
    permission_classes=[IsAuthenticated]

class SaleSettingsViewSet(viewsets.ModelViewSet):
    queryset = SaleSettings.objects.all()
    serializer_class = SaleSettingsSerializer
    permission_classes=[IsAuthenticated]

    def get_queryset(self,request):
        queryset=super().get_queryset()
        return queryset.filter(location__owner=request.user)

class PrefixSettingsViewSet(viewsets.ModelViewSet):
    queryset = PrefixSettings.objects.all()
    serializer_class = PrefixSettingsSerializer
    permission_classes=[IsAuthenticated]

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


