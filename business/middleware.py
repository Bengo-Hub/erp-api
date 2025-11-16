from django.contrib.auth import get_user_model
import secrets
from django.db import DatabaseError, connection
from django.db import IntegrityError, transaction
from .models import *
from core.models import Regions, Departments
from addresses.models import DeliveryRegion

User = get_user_model()

class BusinessConfigs:
    def __init__(self, get_response):
        self.get_response = get_response
        # On startup, ensure all businesses have branding settings
        try:
            self.initialize_business_details()
        except Exception as e:
            print(f"Error during initialize_business_details: {e}")
            try:
                connection.close()
            except Exception:
                pass
        try:
            self.initialize_branding_settings()
        except Exception as e:
            print(f"Error during initialize_branding_settings: {e}")
            try:
                connection.close()
            except Exception:
                pass
        # Initialize pickup locations based on business locations
        try:
            self.initialize_pickup_locations()
        except Exception as e:
            print(f"Error during initialize_pickup_locations: {e}")
            try:
                connection.close()
            except Exception:
                pass

    def initialize_business_details(self):
        """Ensure a single business exists and reuse it; idempotent and safe for concurrent runs"""
        try:
            with transaction.atomic():
                # Resolve or create an owner account for the default business
                owner = User.objects.filter(is_superuser=True).first() or User.objects.filter(is_staff=True).first()
                if owner is None:
                    try:
                        owner = User.objects.create_superuser(
                            username='admin',
                            email='admin@codevertexitsolutions.com',
                            first_name='System',
                            last_name='Administrator',
                            password='Admin@2025!'
                        )
                        print(f"✓ Middleware created admin user (password: Admin@2025!)")
                    except Exception as e:
                        print(f"Warning: Could not create admin user in middleware: {e}")
                        owner = User.objects.first()

                # Get or create standardized business by name
                biz, _ = Bussiness.objects.get_or_create(
                    name='Codevertex IT Solutions',
                    defaults={
                        'owner': owner,
                        'start_date': '2024-01-01',
                        'currency': 'KES',
                        'kra_number': 'A123456789X',
                        'business_type': 'limited_company',
                        'county': 'Nairobi'
                    }
                )

                # Ensure there is a default location
                location = biz.location or BusinessLocation.objects.filter(default=True).first()
                if location is None:
                    location, _ = BusinessLocation.objects.get_or_create(
                        city='Nairobi',
                        defaults={
                            'county': 'Nairobi',
                            'state': 'KE',
                            'country': 'KE',
                            'zip_code': '00100',
                            'postal_code': '00100',
                            'website': 'https://www.codevertexafrica.com',
                            'default': True,
                            'is_active': True
                        }
                    )
                if biz.location_id is None:
                    biz.location = location
                    biz.save(update_fields=['location'])

                # Create or reuse default main branch with unique code
                try:
                    branch, _ = Branch.objects.get_or_create(
                        branch_code='MAIN-001',
                        defaults={
                            'business': biz,
                            'location': location,
                            'name': 'Main Branch',
                            'is_active': True,
                            'is_main_branch': True
                        }
                    )
                    # If branch exists but not linked to this business, skip creating a duplicate
                except IntegrityError:
                    branch = Branch.objects.filter(branch_code='MAIN-001').first()

                # Initialize other business settings idempotently
                self.initialize_product_settings(biz)
                PrefixSettings.objects.get_or_create(business=biz)
                # Ensure at least VAT tax rate exists; tax_number is globally unique - reuse if present
                vat = TaxRates.objects.filter(tax_number='T001').first()
                if not vat:
                    try:
                        TaxRates.objects.create(business=biz, tax_name='VAT', tax_number='T001', percentage=16.0)
                    except IntegrityError:
                        pass
                else:
                    if vat.business_id != biz.id:
                        vat.business = biz
                        vat.save(update_fields=['business'])

                print(f"Business ensured: {biz.name}; branch ensured: {(branch.name if branch else 'N/A')}")
                    
        except Exception as e:
            print(f"Error initializing business details: {e}")

    def initialize_branding_settings(self):
        """Ensure all businesses have branding settings (idempotent, no wide atomic)."""
        try:
            for business in Bussiness.objects.all():
                try:
                    BrandingSettings.objects.get_or_create(
                        business=business,
                        defaults={
                            'primary_color_name': 'blue',
                            'surface_name': 'slate',
                            'compact_mode': False,
                            'ripple_effect': True,
                            'border_radius': '4px',
                            'scale_factor': 1.0,
                        },
                    )
                except IntegrityError:
                    # Likely created concurrently
                    print(f"IntegrityError creating branding settings for {business.name}")
                except DatabaseError as db_e:
                    print(f"DatabaseError creating branding for {business.name}: {db_e}")
                    try:
                        connection.close()
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error initializing branding settings: {e}")

    def initialize_pickup_locations(self):
        """Create pickup locations for businesses based on their business locations (idempotent)."""
        try:
            # Cleanup: Remove duplicate DeliveryRegion entries (keep oldest)
            from django.db.models import Count
            duplicates = DeliveryRegion.objects.values('name', 'county').annotate(
                count=Count('id')
            ).filter(count__gt=1)
            
            for dup in duplicates:
                # Keep the first (oldest) region, delete others
                regions = DeliveryRegion.objects.filter(
                    name=dup['name'], 
                    county=dup['county']
                ).order_by('id')
                
                if regions.count() > 1:
                    keep_region = regions.first()
                    delete_regions = regions.exclude(id=keep_region.id)
                    
                    # Update any PickupStations pointing to duplicate regions
                    for region_to_delete in delete_regions:
                        PickupStations.objects.filter(region=region_to_delete).update(region=keep_region)
                    
                    # Now safe to delete duplicates
                    delete_count = delete_regions.count()
                    delete_regions.delete()
                    print(f"Cleaned up {delete_count} duplicate DeliveryRegion entries for {dup['name']}, {dup['county']}")
            
            # Get all businesses with their branches
            businesses = Bussiness.objects.all().prefetch_related('branches__location')
            for business in businesses:
                # Get business branches for this business
                business_branches = business.branches.all()
                for branch in business_branches:
                    location = branch.location
                    # Normalize lookup to reduce duplicates caused by case/whitespace
                    region_name = (location.city or "").strip()
                    county_name = (location.county or "").strip()
                    # Use get_or_create, but guard against MultipleObjectsReturned when legacy duplicates exist
                    try:
                        region, created = DeliveryRegion.objects.get_or_create(
                            name=region_name,
                            county=county_name,
                            defaults={
                                'delivery_charge': 300,
                                'estimated_delivery_days': 3
                            }
                        )
                    except IntegrityError:
                        # Race condition - another worker created it
                        region = DeliveryRegion.objects.filter(
                            name__iexact=region_name, county__iexact=county_name
                        ).order_by('id').first()
                    except Exception as e:
                        # Handle MultipleObjectsReturned or any unexpected get() behavior inside get_or_create
                        if 'MultipleObjectsReturned' in e.__class__.__name__ or 'returned more than one' in str(e):
                            region = DeliveryRegion.objects.filter(
                                name__iexact=region_name, county__iexact=county_name
                            ).order_by('id').first()
                        else:
                            raise
                    # Create pickup station if not exists
                    pickup_exists = PickupStations.objects.filter(
                        business=business, 
                        region=region,
                        pickup_location__icontains=location.city
                    ).exists()
                    if not pickup_exists:
                        try:
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
                        except IntegrityError:
                            # Created concurrently, safe to ignore
                            pass
        except Exception as e:
            print(f"Error initializing pickup locations: {e}")

    def initialize_product_settings(self, business):
        _, created = ProductSettings.objects.get_or_create(business=business)
        
    def __call__(self, request):
        # Process request
        response = self.get_response(request)
        return response
