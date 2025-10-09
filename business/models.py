from django.db import models
from timezone_field import TimeZoneField
from django.core.validators import RegexValidator
from django_countries.fields import CountryField
from django.utils import timezone
from authmanagement.models import CustomUser
from core.validators import validate_kenyan_county, validate_kenyan_postal_code
from decimal import Decimal
User = CustomUser

# Define the Kenyan phone number regex pattern
kenyan_phone_regex = r"^(?:\+?254|0)(?:\d{9}|\d{3}\s\d{3}\s\d{3}|\d{2}\s\d{3}\s\d{3})$"
# Create a RegexValidator instance using the regex pattern
kenyan_phone_validator = RegexValidator(
    regex=kenyan_phone_regex,
    message="Please enter a valid Kenyan phone number."
)

class BusinessLocation(models.Model):
    country = CountryField(blank=True,null=True,default='KE')
    state = CountryField(blank=True,null=True,default='KE')
    city = models.CharField(max_length=250,blank=True,null=True,default='Kisumu')
    zip_code = models.CharField(max_length=250,default='40100')
    postal_code= models.CharField(max_length=250,default='567')
    website = models.CharField(max_length=250,blank=True,null=True,default='codevertexitsolutions.com')
    default=models.BooleanField(default=False)
    
    # Enhanced Kenyan Address Fields
    county = models.CharField(max_length=100, blank=True, null=True, help_text="Kenyan county where location is situated", validators=[validate_kenyan_county])
    constituency = models.CharField(max_length=100, blank=True, null=True, help_text="Constituency within the county")
    ward = models.CharField(max_length=100, blank=True, null=True, help_text="Ward within the constituency")
    street_name = models.CharField(max_length=255, blank=True, null=True, help_text="Street name or road name")
    building_name = models.CharField(max_length=255, blank=True, null=True, help_text="Building name or landmark")
    floor_number = models.CharField(max_length=20, blank=True, null=True, help_text="Floor number or level")
    room_number = models.CharField(max_length=20, blank=True, null=True, help_text="Room number or office number")
    
    # Location Coordinates
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True, help_text="GPS latitude coordinate")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True, help_text="GPS longitude coordinate")
    
    # Location Status
    is_active = models.BooleanField(default=True, help_text="Whether this location is currently active")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.city}({self.id})"

    class Meta:
        db_table = 'business_location'
        verbose_name = 'Business Location'
        verbose_name_plural = 'Business Location'
        indexes = [
            models.Index(fields=['city'], name='idx_bus_loc_name'),
            models.Index(fields=['default'], name='idx_bus_loc_default'),
            models.Index(fields=['county'], name='idx_bus_loc_county'),
            models.Index(fields=['constituency'], name='idx_bus_loc_const'),
            models.Index(fields=['ward'], name='idx_bus_loc_ward'),
            models.Index(fields=['latitude'], name='idx_bus_loc_lat'),
            models.Index(fields=['longitude'], name='idx_bus_loc_lng'),
            models.Index(fields=['is_active'], name='idx_bus_loc_active'),
            models.Index(fields=['created_at'], name='idx_bus_loc_created'),
        ]
    
class Bussiness(models.Model):
    MONTH_CHOICES = (
        ('Jan', 'January'),
        ('Feb', 'February'),
        ('March', 'March'),
        ('Apr', 'April'),
        ('May', 'May'),
        ('Jun', 'June'),
        ('Jul', 'July'),
        ('Aug', 'August'),
        ('Sept', 'September'),
        ('Oct', 'October'),
        ('Nov', 'November'),
        ('Dec', 'December'),
    )
    ACC_METHOD = (
        ('FIFO', 'First In First Out(FIFO)'),
        ('LIFO', 'Last In Last Out(LIFO)'),
    )
    THEME_PRESETS = (
        ('Lara', 'Lara Theme'),
        ('Aura', 'Aura Theme'),
    )
    MENU_MODES = (
        ('static', 'Static'),
        ('overlay', 'Overlay'),
    )
    location=models.ForeignKey(BusinessLocation,on_delete=models.SET_NULL,related_name="businesses",null=True,blank=True)
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="businesses")
    name = models.CharField(max_length=100,default='Yogis Delight')
    start_date=models.DateField(default=timezone.now)
    finacial_year_start_month = models.CharField(max_length=50,choices=MONTH_CHOICES,default="Jan")
    stock_accounting_method = models.CharField(max_length=50, choices=ACC_METHOD, default="FIFO",help_text='Select stock account method')
    currency = models.CharField(max_length=250,default='KES')
    transaction_edit_days=models.IntegerField(default=30,help_text="In Days")
    default_profit_margin=models.DecimalField(max_digits=10,decimal_places=2,default=Decimal('25.00'),help_text="Percentage (%)")
    logo = models.ImageField(upload_to="business/logo",blank=True,null=True)
    watermarklogo=models.ImageField(upload_to="business/logo",blank=True,null=True)
    timezone = TimeZoneField(default = 'Africa/Nairobi')
    
    # Basic branding colors
    business_primary_color = models.CharField(max_length=7, default='#1976D2', help_text="Main brand color (e.g. #1976D2)")
    business_secondary_color = models.CharField(max_length=7, default='#FF5722', help_text="Secondary brand color (e.g. #FF5722)")
    business_text_color = models.CharField(max_length=7, default='#212121', help_text="Text color (e.g. #212121)")
    business_background_color = models.CharField(max_length=7, default='#ffffff', help_text="Background color (e.g. #ffffff)")
    
    # Theme settings
    ui_theme_preset = models.CharField(max_length=20, choices=THEME_PRESETS, default="Lara", help_text="UI theme preset")
    ui_menu_mode = models.CharField(max_length=20, choices=MENU_MODES, default="static", help_text="Menu display mode")
    ui_dark_mode = models.BooleanField(default=False, help_text="Enable dark mode")
    ui_surface_style = models.CharField(max_length=20, default="slate", help_text="Surface style (e.g. slate, stone, soho, etc.)")
    
    # Kenyan Market Specific Fields
    kra_number = models.CharField(max_length=50, blank=True, null=True, help_text="KRA PIN Number for tax compliance")
    business_license_number = models.CharField(max_length=100, blank=True, null=True, help_text="Business license registration number")
    business_license_expiry = models.DateField(blank=True, null=True, help_text="Business license expiration date")
    business_registration_number = models.CharField(max_length=100, blank=True, null=True, help_text="Company registration number")
    business_type = models.CharField(max_length=50, choices=[
        ('sole_proprietorship', 'Sole Proprietorship'),
        ('partnership', 'Partnership'),
        ('limited_company', 'Limited Company'),
        ('public_company', 'Public Company'),
        ('ngo', 'NGO'),
        ('other', 'Other')
    ], default='limited_company', help_text="Type of business entity")
    county = models.CharField(max_length=100, blank=True, null=True, help_text="Kenyan county where business is located", validators=[validate_kenyan_county])
    postal_code = models.CharField(max_length=10, blank=True, null=True, help_text="Postal code for business location", validators=[validate_kenyan_postal_code])
    
    # KRA Integration Fields
    kra_api_enabled = models.BooleanField(default=False, help_text="Enable KRA API integration")
    kra_api_key = models.CharField(max_length=255, blank=True, null=True, help_text="KRA API key for integration")
    kra_api_secret = models.CharField(max_length=255, blank=True, null=True, help_text="KRA API secret for integration")
    kra_last_sync = models.DateTimeField(blank=True, null=True, help_text="Last KRA data synchronization")
    
    # Compliance Tracking
    tax_compliance_status = models.CharField(max_length=20, choices=[
        ('compliant', 'Compliant'),
        ('non_compliant', 'Non-Compliant'),
        ('pending', 'Pending Review'),
        ('exempt', 'Exempt')
    ], default='pending', help_text="Current tax compliance status")
    last_compliance_check = models.DateTimeField(blank=True, null=True, help_text="Last compliance status check")

    def __str__(self):
        return self.name
        
    def get_branding_settings(self):
        """Return all branding settings as a dictionary"""
        try:
            # Get or create the extended branding settings
            branding, created = BrandingSettings.objects.get_or_create(
                business=self,
                defaults={
                    'primary_color_name': 'blue',
                    'surface_name': 'slate'
                }
            )
            
            return {
                'primary_color': self.business_primary_color,
                'secondary_color': self.business_secondary_color,
                'text_color': self.business_text_color,
                'background_color': self.business_background_color,
                'theme_preset': self.ui_theme_preset,
                'menu_mode': self.ui_menu_mode,
                'dark_mode': self.ui_dark_mode,
                'surface_style': self.ui_surface_style,
                'primary_color_name': branding.primary_color_name,
                'surface_name': branding.surface_name,
                'extended_settings': {
                    'compact_mode': branding.compact_mode,
                    'ripple_effect': branding.ripple_effect,
                    'border_radius': branding.border_radius,
                    'scale_factor': branding.scale_factor,
                }
            }
        except Exception as e:
            return {
                'primary_color': self.business_primary_color,
                'secondary_color': self.business_secondary_color,
                'text_color': self.business_text_color,
                'background_color': self.business_background_color,
                'theme_preset': 'Lara',
                'menu_mode': 'static',
                'dark_mode': False,
                'surface_style': 'slate',
                'primary_color_name': 'blue',
                'surface_name': 'slate',
                'error': str(e)
            }

    class Meta:
        db_table = 'business_details'
        verbose_name = 'Business Details'
        verbose_name_plural = 'Business Details'
        indexes = [
            models.Index(fields=['owner'], name='idx_business_owner'),
            models.Index(fields=['location'], name='idx_business_location'),
            models.Index(fields=['name'], name='idx_business_name'),
            models.Index(fields=['start_date'], name='idx_business_start_date'),
            models.Index(fields=['kra_number'], name='idx_business_kra_number'),
            models.Index(fields=['business_license_number'], name='idx_business_license_number'),
            models.Index(fields=['business_license_expiry'], name='idx_business_license_expiry'),
            models.Index(fields=['business_registration_number'], name='idx_business_reg_number'),
            models.Index(fields=['business_type'], name='idx_business_type'),
            models.Index(fields=['county'], name='idx_business_county'),
            models.Index(fields=['postal_code'], name='idx_business_postal_code'),
            models.Index(fields=['kra_api_enabled'], name='idx_business_kra_api_enabled'),
            models.Index(fields=['tax_compliance_status'], name='idx_business_tax_comp_status'),
            models.Index(fields=['last_compliance_check'], name='idx_business_last_comp_check'),
        ]

class Branch(models.Model):
    business=models.ForeignKey(Bussiness,on_delete=models.CASCADE,related_name='branches')
    location=models.ForeignKey(BusinessLocation,on_delete=models.CASCADE,related_name="branches")
    name=models.CharField(max_length=100,default="Main Branch")
    branch_code=models.CharField(max_length=100,default="MB00100",unique=True)
    contact_number = models.CharField(max_length=15,default='+254743793901',validators=[kenyan_phone_validator])
    alternate_contact_number = models.CharField(max_length=15,default='+254743793901',validators=[kenyan_phone_validator],blank=True,null=True)
    email=models.EmailField(max_length=255,default='info@codevertexitsolutions.com')
     # Business Hours (Kenyan format)
    opening_hours = models.CharField(max_length=255, default="Monday-Friday: 8:00 AM - 5:00 PM", help_text="Business operating hours")
    is_24_hours = models.BooleanField(default=False, help_text="Whether location operates 24/7")
    
    # Additional Contact Information
    whatsapp_number = models.CharField(max_length=15, blank=True, null=True, validators=[kenyan_phone_validator], help_text="WhatsApp business number")
    landline_number = models.CharField(max_length=15, blank=True, null=True, help_text="Landline phone number")
    
    is_active=models.BooleanField(default=True)
    is_main_branch = models.BooleanField(default=False, help_text="Whether this is the main business branch")
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name},{self.business.name} -{self.location.city}({self.branch_code})"
    
    class Meta:
        db_table = 'business_branches'
        verbose_name = 'Branch'
        verbose_name_plural = 'Business Branches'
        indexes = [
            models.Index(fields=['business'], name='idx_branches_business'),
            models.Index(fields=['location'], name='idx_branches_location'),
            models.Index(fields=['is_active'], name='idx_branches_active'),
            models.Index(fields=['created_at'], name='idx_branches_created_at'),
            models.Index(fields=['updated_at'], name='idx_branches_updated_at'),
        ]

class BrandingSettings(models.Model):
    """
    Extended branding settings for business UI customization.
    This model stores the detailed theme configuration that connects
    with the PrimeVue theme system.
    """
    COLOR_NAMES = (
        ('blue', 'Blue'),
        ('green', 'Green'),
        ('yellow', 'Yellow'),
        ('cyan', 'Cyan'),
        ('pink', 'Pink'),
        ('indigo', 'Indigo'),
        ('teal', 'Teal'),
        ('orange', 'Orange'),
        ('bluegray', 'Blue Gray'),
        ('purple', 'Purple'),
        ('red', 'Red'),
        ('amber', 'Amber'), 
    )
    
    SURFACE_NAMES = (
        ('slate', 'Slate'),
        ('zinc', 'Zinc'),
        ('stone', 'Stone'),
        ('soho', 'Soho'),
        ('vela', 'Vela'),
        ('arya', 'Arya'),
        ('concord', 'Concord'),
        ('fluent', 'Fluent'),
        ('noir', 'Noir'),
        ('ocean', 'Ocean'),
    )
    
    business = models.OneToOneField(Bussiness, on_delete=models.CASCADE, related_name='branding')
    
    # PrimeVue theme specific settings
    primary_color_name = models.CharField(max_length=20, choices=COLOR_NAMES, default='blue',
                                         help_text="Color name for PrimeVue theme")
    surface_name = models.CharField(max_length=20, choices=SURFACE_NAMES, default='slate',
                                  help_text="Surface style name for PrimeVue theme")
    
    # Additional UI preferences
    compact_mode = models.BooleanField(default=False, help_text="Use compact mode for UI elements")
    ripple_effect = models.BooleanField(default=True, help_text="Enable ripple effect on clickable elements")
    border_radius = models.CharField(max_length=10, default="4px", help_text="Border radius for UI elements (e.g. 4px)")
    scale_factor = models.FloatField(default=1.0, help_text="UI scaling factor (1.0 = normal)")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Branding for {self.business.name}"
    
    class Meta:
        db_table = 'business_branding_settings'
        verbose_name = 'Branding Settings'
        verbose_name_plural = 'Branding Settings'
        indexes = [
            models.Index(fields=['business'], name='idx_branding_business'),
            models.Index(fields=['created_at'], name='idx_branding_created_at'),
            models.Index(fields=['updated_at'], name='idx_branding_updated_at'),
        ]
        

class TaxRates(models.Model):
    business=models.ForeignKey(Bussiness,on_delete=models.CASCADE,related_name="taxrates")
    tax_name = models.CharField(max_length=50,default='VAT')
    tax_number = models.CharField(max_length=50,default='T001',unique=True)
    percentage = models.DecimalField(max_digits=10,decimal_places=2,default=Decimal('16.00'))

    def __str__(self):
        return self.tax_name

    class Meta:
        db_table = 'taxrates'
        verbose_name = 'Tax Rates'
        verbose_name_plural = 'Tax Rates'
        indexes = [
            models.Index(fields=['business'], name='idx_business_tax_business'),
            models.Index(fields=['tax_number'], name='idx_business_tax_number'),
        ]

class ProductSettings(models.Model):
    business=models.ForeignKey(Bussiness,on_delete=models.CASCADE,related_name="productsettings")
    default_unit=models.CharField(max_length=100,default="Piece(s)")
    enable_warranty=models.BooleanField(default=False)
    enable_product_expiry=models.BooleanField(default=False)
    stop_selling_days_before_expiry=models.IntegerField(default=1)
    sku_prefix=models.CharField(max_length=20,default="BH")

    def __str__(self):
        return 'Product Setting'

    class Meta:
        db_table = 'product_settings'
        verbose_name = 'Product Settings'
        verbose_name_plural = 'Product Settings'
        indexes = [
            models.Index(fields=['business'], name='idx_product_settings_business'),
        ]

class SaleSettings(models.Model):
    business=models.ForeignKey(Bussiness,on_delete=models.CASCADE,related_name="salesettings")
    default_discount=models.DecimalField(max_digits=10,decimal_places=2,default=Decimal('0.00'))
    default_tax=models.ForeignKey(TaxRates,on_delete=models.SET_NULL,null=True,default=None)

    def __str__(self):
        return 'Sale Setting'

    class Meta:
        db_table = 'sale_settings'
        verbose_name = 'Sale Settings'
        verbose_name_plural = 'Sale Settings'
        indexes = [
            models.Index(fields=['business'], name='idx_sale_settings_business'),
        ]

class PrefixSettings(models.Model):
    business=models.ForeignKey(Bussiness,on_delete=models.CASCADE,related_name="prefixsettings")
    purchase=models.CharField(max_length=5,default="P")
    purchase_order=models.CharField(max_length=5,default="PO")
    purchase_return=models.CharField(max_length=5,default="PRT")
    purchase_requisition=models.CharField(max_length=5,default="PRQ")
    stock_transfer=models.CharField(max_length=5,default="ST")
    sale_return=models.CharField(max_length=5,default="SR")
    expense=models.CharField(max_length=5,default="EP")
    business_location=models.CharField(max_length=5,default="BL")

    def __str__(self):
        return 'Prefix Setting'

    class Meta:
        db_table = 'prefix_settings'
        verbose_name = 'Prefix Settings'
        verbose_name_plural = 'Prefix Settings'
        indexes = [
            models.Index(fields=['business'], name='idx_prefix_settings_business'),
        ]

class ServiceTypes(models.Model):
    business=models.ForeignKey(Bussiness,on_delete=models.CASCADE,related_name="servicetypes")
    name=models.CharField(max_length=255)
    description=models.CharField(max_length=255)
    packing_charge_type=models.CharField(max_length=50,choices=[("Fixed","Fixed"),("Percentage","Percentage")],default="Fixed")
    packing_charge=models.IntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'service_types'
        verbose_name = 'Service Types'
        verbose_name_plural = 'Service Types'
        indexes = [
            models.Index(fields=['business'], name='idx_service_types_business'),
            models.Index(fields=['name'], name='idx_service_types_name'),
        ]

class PickupStations(models.Model):
    business = models.ForeignKey(Bussiness, on_delete=models.CASCADE, related_name='pickup_stations')
    region = models.ForeignKey('addresses.DeliveryRegion', on_delete=models.CASCADE, related_name='pickupstations', blank=True, null=True)
    pickup_location = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    
    # Business Delivery Settings
    is_active = models.BooleanField(default=True, help_text="Whether this pickup station is currently active")
    priority_order = models.PositiveIntegerField(default=0, help_text="Higher number means higher priority in listings")
    delivery_radius_km = models.PositiveIntegerField(default=5, help_text="Delivery radius in kilometers from this station")
    
    # Operating Hours
    open_hours = models.CharField(max_length=255, default="Mon-Fri 0800hrs - 1700hrs;Sat 0800hrs - 1300hrs")
    is_24_hours = models.BooleanField(default=False, help_text="Whether station operates 24/7")
    
    # Payment and Contact
    payment_options = models.CharField(max_length=500, default="MPESA On Delivery, Cards")
    helpline = models.CharField(max_length=20, default="076353535353")
    whatsapp_number = models.CharField(max_length=15, blank=True, null=True, help_text="WhatsApp number for customer support")
    
    # Location Details
    google_pin = models.URLField(max_length=1500, default="https://goo.gl/maps/p2QAwb7jbmxuJcb36")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True, help_text="GPS latitude coordinate")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True, help_text="GPS longitude coordinate")
    postal_code = models.CharField(max_length=100, default="57-40100", blank=True, null=True, validators=[validate_kenyan_postal_code])
    
    # Pricing
    shipping_charge = models.PositiveBigIntegerField(default=85, help_text="Shipping charge for this pickup station")
    free_delivery_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Order amount above which delivery is free")
    
    # Status and Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.pickup_location} ({self.business.name})"

    class Meta:
        managed = True
        db_table = "pickup_stations"
        verbose_name_plural = "Pickup Stations"
        ordering = ['-priority_order', 'pickup_location']
        indexes = [
            models.Index(fields=['business'], name='idx_pickup_stations_business'),
            models.Index(fields=['region'], name='idx_pickup_stations_region'),
            models.Index(fields=['is_active'], name='idx_pickup_stations_active'),
            models.Index(fields=['priority_order'], name='idx_pickup_stations_priority'),
            models.Index(fields=['latitude'], name='idx_pickup_stations_latitude'),
            models.Index(fields=['longitude'], name='idx_pickup_stations_longitude'),
            models.Index(fields=['created_at'], name='idx_pickup_stations_created'),
        ]
    
    @property
    def is_free_delivery_available(self):
        """Check if free delivery is available at this station"""
        return self.free_delivery_threshold > 0
    
    @property
    def operating_hours_display(self):
        """Get formatted operating hours"""
        if self.is_24_hours:
            return "24/7"
        return self.open_hours
    
    def calculate_delivery_charge(self, order_amount=0):
        """Calculate delivery charge based on order amount"""
        if order_amount >= self.free_delivery_threshold and self.free_delivery_threshold > 0:
            return 0
        return self.shipping_charge

# AddressBook moved to addresses app - import from there
# from addresses.models import AddressBook
