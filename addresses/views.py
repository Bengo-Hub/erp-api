from django.shortcuts import render
from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from django_filters import rest_framework as filters
from django.db.models import Q
from .models import AddressBook, DeliveryRegion, AddressValidation
from .serializers import (
    AddressBookSerializer, AddressBookListSerializer, AddressBookCreateSerializer,
    DeliveryRegionSerializer, DeliveryRegionListSerializer, AddressValidationSerializer
)
from django.contrib.auth import get_user_model


class AddressBookFilter(filters.FilterSet):
    """Filter for AddressBook"""
    address_type = filters.CharFilter(lookup_expr='icontains')
    delivery_type = filters.CharFilter(lookup_expr='icontains')
    county = filters.CharFilter(lookup_expr='icontains')
    city = filters.CharFilter(lookup_expr='icontains')
    is_default = filters.BooleanFilter()
    is_active = filters.BooleanFilter()
    user = filters.ModelChoiceFilter(queryset=get_user_model().objects.all())
    
    class Meta:
        model = AddressBook
        fields = ['address_type', 'delivery_type', 'county', 'city', 'is_default', 'is_active', 'user']


class AddressBookViewSet(viewsets.ModelViewSet):
    """ViewSet for AddressBook model"""
    queryset = AddressBook.objects.all()
    serializer_class = AddressBookSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = AddressBookFilter
    
    def get_serializer_class(self):
        if self.action == 'create':
            return AddressBookCreateSerializer
        elif self.action == 'list':
            return AddressBookListSerializer
        return AddressBookSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # If user is not superuser, only show their addresses
        if not user.is_superuser:
            queryset = queryset.filter(Q(user=user))

        # Only select related fields that actually exist on the model to avoid FieldError
        # AddressBook has FKs: user, pickup_station, verified_by and related_name 'validations'
        return queryset.select_related('user', 'pickup_station', 'verified_by').prefetch_related('validations')
    
    def perform_create(self, serializer):
        serializer.save()
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set an address as default for the user"""
        address = self.get_object()
        user = request.user
        
        # Unset other default addresses for the same user
        AddressBook.objects.filter(
            Q(user=user) | Q(contact__user=user),
            is_default=True
        ).exclude(id=address.id).update(is_default=False)
        
        # Set this address as default
        address.is_default = True
        address.save()
        
        return Response({'status': 'Address set as default'})
    
    @action(detail=True, methods=['post'])
    def validate_address(self, request, pk=None):
        """Trigger address validation"""
        address = self.get_object()
        
        # Create or update validation record
        validation, created = AddressValidation.objects.get_or_create(
            address=address,
            defaults={'validation_status': 'pending'}
        )
        
        # Here you would typically call an external validation service
        # For now, we'll simulate validation
        validation.validation_status = 'validated'
        validation.validation_notes = 'Address validated successfully'
        validation.save()
        
        return Response({'status': 'Address validation completed'})
    
    @action(detail=False, methods=['get'])
    def my_addresses(self, request):
        """Get addresses for the current user"""
        user = request.user
        addresses = self.get_queryset().filter(Q(user=user))
        
        serializer = self.get_serializer(addresses, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def default_address(self, request):
        """Get the default address for the current user"""
        user = request.user
        default_address = self.get_queryset().filter(Q(user=user), is_default=True).first()
        
        if default_address:
            serializer = self.get_serializer(default_address)
            return Response(serializer.data)
        else:
            return Response({'error': 'No default address found'}, status=status.HTTP_404_NOT_FOUND)


class DeliveryRegionFilter(filters.FilterSet):
    """Filter for DeliveryRegion"""
    name = filters.CharFilter(lookup_expr='icontains')
    county = filters.CharFilter(lookup_expr='icontains')
    constituency = filters.CharFilter(lookup_expr='icontains')
    ward = filters.CharFilter(lookup_expr='icontains')
    is_active = filters.BooleanFilter()
    
    class Meta:
        model = DeliveryRegion
        fields = ['name', 'county', 'constituency', 'ward', 'is_active']


class DeliveryRegionViewSet(viewsets.ModelViewSet):
    """ViewSet for DeliveryRegion model"""
    queryset = DeliveryRegion.objects.all()
    serializer_class = DeliveryRegionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = DeliveryRegionFilter
    
    def get_serializer_class(self):
        if self.action == 'list':
            return DeliveryRegionListSerializer
        return DeliveryRegionSerializer
    
    def get_queryset(self):
        return super().get_queryset().prefetch_related('pickup_stations')
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a delivery region"""
        region = self.get_object()
        region.is_active = True
        region.save()
        return Response({'status': 'Delivery region activated'})
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a delivery region"""
        region = self.get_object()
        region.is_active = False
        region.save()
        return Response({'status': 'Delivery region deactivated'})
    
    @action(detail=False, methods=['get'])
    def active_regions(self, request):
        """Get all active delivery regions"""
        active_regions = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(active_regions, many=True)
        return Response(serializer.data)


class AddressValidationViewSet(viewsets.ModelViewSet):
    """ViewSet for AddressValidation model"""
    queryset = AddressValidation.objects.all()
    serializer_class = AddressValidationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    
    def get_queryset(self):
        return super().get_queryset().select_related('address')
    
    @action(detail=True, methods=['post'])
    def revalidate(self, request, pk=None):
        """Revalidate an address"""
        validation = self.get_object()
        validation.validation_status = 'pending'
        validation.validation_notes = ''
        validation.save()
        
        # Here you would typically call an external validation service
        # For now, we'll simulate validation
        validation.validation_status = 'validated'
        validation.validation_notes = 'Address revalidated successfully'
        validation.save()
        
        return Response({'status': 'Address revalidation completed'})
