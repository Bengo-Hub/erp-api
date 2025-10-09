from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.validators import validate_kenyan_county, validate_kenyan_postal_code
from decimal import Decimal
from business.models import PickupStations

User = get_user_model()


class AddressBook(models.Model):
    """
    Centralized Address Management - User Addresses (Jumia-style)
    Moved from business app to addresses app for proper separation
    """
    ADDRESS_TYPE_CHOICES = [
        ('shipping', 'Shipping Address'),
        ('billing', 'Billing Address'),
        ('both', 'Shipping & Billing Address'),
    ]
    
    DELIVERY_TYPE_CHOICES = [
        ('home', 'Home Delivery'),
        ('pickup', 'Pickup Station'),
        ('office', 'Office Delivery'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    address_label = models.CharField(max_length=255, default='My Address')
    address_type = models.CharField(max_length=20, choices=ADDRESS_TYPE_CHOICES, default='both')
    
    # Contact Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    other_phone = models.CharField(max_length=15, blank=True, null=True)
    
    # Kenyan Address Structure (Jumia-style)
    county = models.CharField(max_length=100, help_text="Kenyan county (e.g., Nairobi, Mombasa, Kisumu)", validators=[validate_kenyan_county])
    constituency = models.CharField(max_length=100, blank=True, null=True, help_text="Constituency within the county")
    ward = models.CharField(max_length=100, blank=True, null=True, help_text="Ward within the constituency")
    street_name = models.CharField(max_length=255, help_text="Street name or road name")
    building_name = models.CharField(max_length=255, blank=True, null=True, help_text="Building name or landmark")
    floor_number = models.CharField(max_length=20, blank=True, null=True, help_text="Floor number or level")
    room_number = models.CharField(max_length=20, blank=True, null=True, help_text="Room number or office number")
    postal_code = models.CharField(max_length=10, help_text="Postal code", validators=[validate_kenyan_postal_code])
    country = models.CharField(max_length=100, default='Kenya')
    
    # GPS Coordinates
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True, help_text="GPS latitude coordinate")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True, help_text="GPS longitude coordinate")
    
    # Delivery Options
    delivery_type = models.CharField(max_length=20, choices=DELIVERY_TYPE_CHOICES, default='home', help_text="Preferred delivery method")
    pickup_station = models.ForeignKey('business.PickupStations', on_delete=models.SET_NULL, blank=True, null=True, related_name='pickup_addresses', help_text="Selected pickup station if delivery_type is pickup")
    
    # Default flags
    is_default_shipping = models.BooleanField(default=False, verbose_name="Default Shipping Address")
    is_default_billing = models.BooleanField(default=False, verbose_name="Default Billing Address")
    
    # Validation and status
    is_verified = models.BooleanField(default=False, help_text="Whether address has been verified")
    verification_date = models.DateTimeField(blank=True, null=True, help_text="When address was verified")
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_addresses')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Ensure only one default shipping address per user
        if self.is_default_shipping:
            AddressBook.objects.filter(user=self.user, is_default_shipping=True).exclude(pk=self.pk).update(is_default_shipping=False)
        
        # Ensure only one default billing address per user
        if self.is_default_billing:
            AddressBook.objects.filter(user=self.user, is_default_billing=True).exclude(pk=self.pk).update(is_default_billing=False)
            
        super().save(*args, **kwargs)

    class Meta:
        db_table = "address_book"
        managed = True
        verbose_name = "Address"
        verbose_name_plural = "Address Book"
        indexes = [
            models.Index(fields=['user'], name='idx_address_user'),
            models.Index(fields=['address_type'], name='idx_address_type'),
            models.Index(fields=['delivery_type'], name='idx_address_delivery_type'),
            models.Index(fields=['county'], name='idx_address_county'),
            models.Index(fields=['constituency'], name='idx_address_constituency'),
            models.Index(fields=['is_default_shipping'], name='idx_address_default_shipping'),
            models.Index(fields=['is_default_billing'], name='idx_address_default_billing'),
            models.Index(fields=['is_verified'], name='idx_address_verified'),
            models.Index(fields=['created_at'], name='idx_address_created_at'),
        ]

    def __str__(self):
        if self.delivery_type == 'pickup' and self.pickup_station:
            return f"{self.address_label} (Pickup: {self.pickup_station.pickup_location})"
        return f"{self.address_label} - {self.street_name}, {self.county}"
    
    @property
    def full_address(self):
        """Get formatted full address string"""
        parts = []
        if self.building_name:
            parts.append(self.building_name)
        if self.floor_number:
            parts.append(f"Floor {self.floor_number}")
        if self.room_number:
            parts.append(f"Room {self.room_number}")
        if self.street_name:
            parts.append(self.street_name)
        if self.ward:
            parts.append(f"Ward {self.ward}")
        if self.constituency:
            parts.append(f"{self.constituency} Constituency")
        if self.county:
            parts.append(f"{self.county} County")
        if self.postal_code:
            parts.append(self.postal_code)
        if self.country:
            parts.append(self.country)
        
        return ", ".join(parts)
    
    @property
    def contact_name(self):
        """Get formatted contact name"""
        return f"{self.first_name} {self.last_name}"
    
    @property
    def is_pickup_delivery(self):
        """Check if this is a pickup delivery address"""
        return self.delivery_type == 'pickup' and self.pickup_station is not None
    
    @property
    def is_home_delivery(self):
        """Check if this is a home delivery address"""
        return self.delivery_type == 'home'
    
    @property
    def is_office_delivery(self):
        """Check if this is an office delivery address"""
        return self.delivery_type == 'office'


class DeliveryRegion(models.Model):
    """
    Delivery Regions - For organizing delivery areas and pickup stations
    """
    name = models.CharField(max_length=255, help_text="Name of the delivery region")
    county = models.CharField(max_length=100, help_text="County this region belongs to")
    description = models.TextField(blank=True, null=True)
    
    # Delivery settings
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Standard delivery charge for this region")
    free_delivery_threshold = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, help_text="Order amount for free delivery")
    estimated_delivery_days = models.PositiveIntegerField(default=3, help_text="Estimated delivery time in days")
    
    # Coverage
    is_active = models.BooleanField(default=True)
    covers_counties = models.JSONField(default=list, blank=True, help_text="List of counties covered by this region")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'delivery_regions'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name'], name='idx_delivery_region_name'),
            models.Index(fields=['county'], name='idx_delivery_region_county'),
            models.Index(fields=['is_active'], name='idx_delivery_region_active'),
        ]

    def __str__(self):
        return f"{self.name} ({self.county})"
    
    @property
    def pickup_stations_count(self):
        """Get number of pickup stations in this region"""
        try:
            return PickupStations.objects.filter(region=self).count()
        except Exception:
            return 0
    
    @property
    def is_free_delivery_available(self):
        """Check if free delivery is available"""
        return self.free_delivery_threshold is not None


class AddressValidation(models.Model):
    """
    Address Validation - Track address validation attempts and results
    """
    VALIDATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('validated', 'Validated'),
        ('invalid', 'Invalid'),
        ('partial', 'Partially Valid'),
        ('failed', 'Validation Failed'),
    ]
    
    address = models.ForeignKey(AddressBook, on_delete=models.CASCADE, related_name='validations')
    validator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='address_validations')
    
    # Validation details
    status = models.CharField(max_length=20, choices=VALIDATION_STATUS_CHOICES, default='pending')
    validation_method = models.CharField(max_length=50, choices=[
        ('manual', 'Manual Verification'),
        ('api', 'API Validation'),
        ('gps', 'GPS Verification'),
        ('postal', 'Postal Code Verification'),
    ], default='manual')
    
    # Results
    is_valid = models.BooleanField(default=False)
    confidence_score = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, help_text="Validation confidence score (0-1)")
    validation_notes = models.TextField(blank=True, null=True)
    
    # Timestamps
    validated_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'address_validations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['address'], name='idx_address_validation_address'),
            models.Index(fields=['status'], name='idx_address_validation_status'),
            models.Index(fields=['is_valid'], name='idx_address_validation_valid'),
            models.Index(fields=['validated_at'], name='idx_addr_validated_at'),
        ]

    def __str__(self):
        return f"Validation for {self.address} - {self.status}"
    
    def validate(self, validator=None, method='manual', notes=None):
        """Mark address as validated"""
        self.status = 'validated'
        self.is_valid = True
        self.validator = validator
        self.validation_method = method
        self.validated_at = timezone.now()
        if notes:
            self.validation_notes = notes
        self.save()
        
        # Update address verification status
        self.address.is_verified = True
        self.address.verification_date = timezone.now()
        self.address.verified_by = validator
        self.address.save()
    
    def invalidate(self, validator=None, notes=None):
        """Mark address as invalid"""
        self.status = 'invalid'
        self.is_valid = False
        self.validator = validator
        self.validated_at = timezone.now()
        if notes:
            self.validation_notes = notes
        self.save()
