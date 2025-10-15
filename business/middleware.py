from django.contrib.auth import get_user_model
import secrets
from django.db import IntegrityError, transaction
from .models import *
from core.models import Regions, Departments
from addresses.models import DeliveryRegion

User = get_user_model()

class BusinessConfigs:
    def __init__(self, get_response):
        self.get_response = get_response
        # On startup, ensure all businesses have branding settings
        self.initialize_business_details()
        self.initialize_branding_settings()
        # Initialize pickup locations based on business locations
        self.initialize_pickup_locations()

    def initialize_business_details(self):
        """Ensure all businesses have business details and proper multi-branch structure"""
        try:
            with transaction.atomic():
                if Bussiness.objects.count() == 0:
                    # Resolve or create an owner account for the default business
                    owner = User.objects.filter(is_superuser=True).first()
                    if owner is None:
                        owner = User.objects.filter(is_staff=True).first()
                    if owner is None:
                        # Create a secure superuser if none exists
                        try:
                            random_password = secrets.token_urlsafe(20)
                            owner = User.objects.create_superuser(
                                username='admin',
                                email='admin@codevertexafrica.com',
                                password=random_password
                            )
                        except Exception:
                            # Fallback to any existing user if creation fails
                            owner = User.objects.first()

                    # Create default business location
                    location = BusinessLocation.objects.create(
                        city='Nairobi',
                        county='Nairobi',
                        state='KE',
                        country='KE',
                        zip_code='00100',
                        postal_code='00100',
                        website='codevertexitsolutions.com',
                        default=True,
                        is_active=True
                    )
                    
                    # Create default business
                    biz = Bussiness.objects.create(
                        location=location,
                        owner=owner,
                        name='Codevertex Africa',
                        start_date='2024-01-01',
                        currency='KES',
                        kra_number='A123456789X',
                        business_type='limited_company',
                        county='Nairobi'
                    )
                    
                
                    # Create default branch
                    branch = Branch.objects.create(
                        business=biz,
                        location=location,
                        name='Nairobi Main Branch',
                        branch_code='NBO-MAIN-001',
                        is_active=True,
                        is_main_branch=True
                    )
                    
                    # Initialize other business settings
                    self.initialize_product_settings(biz)
                    _, created = PrefixSettings.objects.get_or_create(business=biz)
                    _, created = TaxRates.objects.get_or_create(business=biz)
                    
                    print(f"Created default business: {biz.name} with branch: {branch.name}")
                    
        except Exception as e:
            print(f"Error initializing business details: {e}")

    def initialize_branding_settings(self):
        """Ensure all businesses have branding settings"""
        try:
            with transaction.atomic():
                # Get all businesses that don't have branding settings
                businesses_without_branding = []
                for business in Bussiness.objects.all():
                    if not hasattr(business, 'branding'):
                        businesses_without_branding.append(business)
                
                # Create branding settings for each business that needs it
                for business in businesses_without_branding:
                    try:
                        # Check if a branding setting exists but isn't properly linked
                        existing = BrandingSettings.objects.filter(business=business).first()
                        if existing:
                            continue
                            
                        # Create new branding settings
                        BrandingSettings.objects.create(
                            business=business,
                            primary_color_name='blue',
                            surface_name='slate',
                            compact_mode=False,
                            ripple_effect=True,
                            border_radius='4px',
                            scale_factor=1.0
                        )
                    except IntegrityError:
                        # If there's an integrity error, it likely means another process created it
                        # Just log and continue
                        print(f"IntegrityError creating branding settings for {business.name}")
        except Exception as e:
            print(f"Error initializing branding settings: {e}")

    def initialize_pickup_locations(self):
        """Create pickup locations for businesses based on their business locations"""
        try:
            with transaction.atomic():
                # Get all businesses with their branches
                businesses = Bussiness.objects.all().prefetch_related('branches__location')
                
                for business in businesses:
                    # Get business branches for this business
                    business_branches = business.branches.all()
                    
                    # For each business branch, ensure a DeliveryRegion and PickupStation exists
                    for branch in business_branches:
                        location = branch.location
                        
                        # Get or create delivery region for this location
                        region, created = DeliveryRegion.objects.get_or_create(
                            name=location.city,
                            county=location.county,
                            defaults={
                                'delivery_charge': 300,
                                'estimated_delivery_days': 3
                            }
                        )
                        
                        # Check if a pickup station already exists for this business and region
                        pickup_exists = PickupStations.objects.filter(
                            business=business, 
                            region=region,
                            pickup_location__icontains=location.city
                        ).exists()
                        
                        # Only create if it doesn't exist already
                        if not pickup_exists:
                            # Create the pickup station
                            PickupStations.objects.create(
                                business=business,
                                region=region,
                                pickup_location=f"{location.city} Pickup Point",
                                description=f"Official pickup point at {location.city}",
                                open_hours="Mon-Fri 0800hrs - 1700hrs;Sat 0800hrs - 1300hrs",
                                payment_options="MPESA On Delivery, Cards",
                                google_pin=location.google_pin if hasattr(location, 'google_pin') and location.google_pin else "",
                                helpline=location.contact_number if hasattr(location, 'contact_number') and location.contact_number else "076353535353",
                                shipping_charge=100,
                                postal_code=location.postal_code if hasattr(location, 'postal_code') and location.postal_code else "57-40100"
                            )
        except Exception as e:
            print(f"Error initializing pickup locations: {e}")

    def initialize_product_settings(self, business):
        _, created = ProductSettings.objects.get_or_create(business=business)
        
    def __call__(self, request):
        # Process request
        response = self.get_response(request)
        return response
