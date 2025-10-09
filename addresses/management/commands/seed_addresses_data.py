from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from addresses.models import AddressBook
from business.models import Bussiness, BusinessLocation
from authmanagement.models import CustomUser

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds addresses data including address books and validation rules'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting to seed addresses data...'))
        
        # Note: DeliveryRegion and PickupStations are created by middleware
        # We only need to seed data that is NOT automatically created by middleware
        
        # Get existing business (created by middleware)
        business = Bussiness.objects.first()
        if not business:
            self.stdout.write(self.style.ERROR('No business found. Please ensure middleware has run first.'))
            return
        
        # Get existing business location (created by middleware)
        location = BusinessLocation.objects.filter(default=True, is_active=True).first()
        if not location:
            self.stdout.write(self.style.WARNING('No business location found. Creating default location...'))
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
        
        # Ensure admin user exists for address creation
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            admin_user = User.objects.create_superuser(
                username='admin', 
                email='admin@example.com', 
                password='admin123'
            )
            self.stdout.write(self.style.SUCCESS('Created admin user'))
        
        # Create sample address books
        address_books_data = [
            {
                'address_label': 'Home Address',
                'address_type': 'both',
                'first_name': 'John',
                'last_name': 'Doe',
                'phone': '+254700000001',
                'email': 'john.doe@example.com',
                'county': 'Nairobi',
                'constituency': 'Westlands',
                'ward': 'Parklands',
                'street_name': 'Main Street',
                'building_name': 'Excel Building',
                'postal_code': '00100',
                'country': 'Kenya',
                'delivery_type': 'home',
                'is_default_shipping': True,
                'is_default_billing': True
            },
            {
                'address_label': 'Office Address',
                'address_type': 'billing',
                'first_name': 'Jane',
                'last_name': 'Smith',
                'phone': '+254700000002',
                'email': 'jane.smith@supplier.com',
                'county': 'Nairobi',
                'constituency': 'Kilimani',
                'ward': 'Kilimani',
                'street_name': 'Business Avenue',
                'building_name': 'Business Plaza',
                'postal_code': '00200',
                'country': 'Kenya',
                'delivery_type': 'office',
                'is_default_shipping': False,
                'is_default_billing': False
            },
            {
                'address_label': 'Mombasa Branch',
                'address_type': 'both',
                'first_name': 'ABC',
                'last_name': 'Company Ltd',
                'phone': '+254700000003',
                'email': 'info@abccompany.com',
                'county': 'Mombasa',
                'constituency': 'Mvita',
                'ward': 'Mvita',
                'street_name': 'Industrial Road',
                'building_name': 'Industrial Complex',
                'postal_code': '80100',
                'country': 'Kenya',
                'delivery_type': 'pickup',
                'is_default_shipping': False,
                'is_default_billing': False
            },
            {
                'address_label': 'Kisumu Office',
                'address_type': 'shipping',
                'first_name': 'XYZ',
                'last_name': 'Corporation',
                'phone': '+254700000004',
                'email': 'sales@xyzcorp.com',
                'county': 'Kisumu',
                'constituency': 'Kisumu Central',
                'ward': 'Kisumu Central',
                'street_name': 'Corporate Drive',
                'building_name': 'Corporate Tower',
                'postal_code': '40100',
                'country': 'Kenya',
                'delivery_type': 'office',
                'is_default_shipping': False,
                'is_default_billing': False
            }
        ]
        
        for address_data in address_books_data:
            address_book, created = AddressBook.objects.get_or_create(
                user=admin_user,
                address_label=address_data['address_label'],
                defaults={
                    'address_type': address_data['address_type'],
                    'first_name': address_data['first_name'],
                    'last_name': address_data['last_name'],
                    'phone': address_data['phone'],
                    'email': address_data['email'],
                    'county': address_data['county'],
                    'constituency': address_data['constituency'],
                    'ward': address_data['ward'],
                    'street_name': address_data['street_name'],
                    'building_name': address_data['building_name'],
                    'postal_code': address_data['postal_code'],
                    'country': address_data['country'],
                    'delivery_type': address_data['delivery_type'],
                    'is_default_shipping': address_data['is_default_shipping'],
                    'is_default_billing': address_data['is_default_billing']
                }
            )
            if created:
                self.stdout.write(f'Created address book entry: {address_book.address_label}')
        
        self.stdout.write(self.style.SUCCESS('Addresses data seeding completed successfully!'))
        self.stdout.write(self.style.SUCCESS('Note: DeliveryRegion and PickupStations are automatically created by middleware'))
