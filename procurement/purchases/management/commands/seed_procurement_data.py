"""
Django management command to seed procurement data
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from datetime import timedelta
from decimal import Decimal

from procurement.orders.models import PurchaseOrder
from procurement.requisitions.models import ProcurementRequest, RequestItem
from procurement.contracts.models import Contract
from business.models import Branch, Bussiness
from ecommerce.stockinventory.models import StockInventory

User = get_user_model()

class Command(BaseCommand):
    help = 'Seed sample procurement data for testing and development'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing procurement data before seeding',
        )
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Seed minimal procurement data (1 requisition, 1 item)',
        )

    def handle(self, *args, **options):
        clear_data = options.get('clear')
        minimal = options.get('minimal')
        
        if clear_data:
            self.stdout.write(self.style.WARNING('Clearing existing procurement data...'))
            self._clear_procurement_data()

        self.stdout.write(self.style.SUCCESS('Starting to seed procurement data...'))
        
        try:
            # Get or create required data
            admin_user = User.objects.filter(is_superuser=True).first()
            if not admin_user:
                admin_user = User.objects.filter(is_staff=True).first()
            if not admin_user:
                admin_user = User.objects.first()
            
            if not admin_user:
                self.stdout.write(self.style.ERROR('No user found to create procurement data'))
                return
            
            business = Bussiness.objects.filter(name__iexact='Codevertex IT Solutions').first() or Bussiness.objects.first()
            if not business:
                self.stdout.write(self.style.ERROR('No business found'))
                return
            
            branch = Branch.objects.filter(business=business, is_main_branch=True).first() or Branch.objects.filter(business=business).first()
            if not branch:
                self.stdout.write(self.style.ERROR('No branch found'))
                return
            
            # Get some products for procurement
            products = StockInventory.objects.filter(stock_level__gt=0)[:10]
            if not products.exists():
                self.stdout.write(self.style.WARNING('No products found for procurement seeding'))
                return
            
            # Create sample requisitions
            self._create_requisitions(admin_user, business, branch, products, minimal=minimal)
            
            # Create sample purchase orders
            self._create_purchase_orders(admin_user, business, branch, products, minimal=minimal)
            
            # Create sample contracts
            self._create_contracts(admin_user, business, branch, products, minimal=minimal)
            
            self.stdout.write(self.style.SUCCESS('✅ Procurement data seeded successfully!'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error seeding procurement data: {str(e)}'))
            raise

    def _create_requisitions(self, user, business, branch, products, minimal=False):
        """Create sample requisitions"""
        self.stdout.write('  Creating sample requisitions...')
        
        requisition_data = [
            {
                'purpose': 'Monthly office supplies including paper, pens, and stationery',
                'priority': 'medium',
                'status': 'approved',
                'requester': user,
                'request_type': 'inventory',
                'required_by_date': timezone.now().date() + timedelta(days=30),
            },
            {
                'purpose': 'New laptops and accessories for development team',
                'priority': 'high',
                'status': 'pending',
                'requester': user,
                'request_type': 'inventory',
                'required_by_date': timezone.now().date() + timedelta(days=15),
            },
            {
                'purpose': 'Banners, brochures, and promotional materials for Q4 campaign',
                'priority': 'medium',
                'status': 'approved',
                'requester': user,
                'request_type': 'inventory',
                'required_by_date': timezone.now().date() + timedelta(days=45),
            }
        ]
        
        for req_data in (requisition_data[:1] if minimal else requisition_data):
            requisition = ProcurementRequest.objects.create(**req_data)
            
            # Add items to requisition
            for i, product in enumerate(products[: (1 if minimal else 3) ]):
                RequestItem.objects.create(
                    request=requisition,
                    item_type='inventory',
                    stock_item=product,
                    quantity=i + 1,
                    approved_quantity=i + 1,
                    description=f'Request for {product.product.title if product.product else "Unknown Product"}'
                )
        
        self.stdout.write(f'    Created {len(requisition_data)} requisitions')

    def _create_purchase_orders(self, user, business, branch, products, minimal=False):
        """Create sample purchase orders"""
        self.stdout.write('  Creating sample purchase orders...')
        
        # Note: PurchaseOrder creation requires a requisition, so we'll create simplified ones
        # In a real scenario, you'd need to create requisitions first and link them
        
        self.stdout.write('    Note: Purchase orders require requisitions to be created first')
        if minimal:
            # In minimal mode we won't create full POs, but log the sample
            self.stdout.write('    Minimal mode: skipping full purchase order creation')
            return
        self.stdout.write('    Skipping purchase order creation for now')
        
        # For now, just create a note that this would need requisitions
        self.stdout.write('    To create purchase orders, first create requisitions and link them')

    def _create_contracts(self, user, business, branch, products, minimal=False):
        """Create sample contracts"""
        self.stdout.write('  Creating sample contracts...')
        
        # Note: Contract creation requires a Contact (supplier), so we'll create simplified ones
        # In a real scenario, you'd need to create supplier contacts first
        
        self.stdout.write('    Note: Contracts require supplier contacts to be created first')
        if minimal:
            # In minimal mode we won't generate sample contracts; log sample
            self.stdout.write('    Minimal mode: skipping contract creation')
            return
        self.stdout.write('    Skipping contract creation for now')
        
        # For now, just create a note that this would need supplier contacts
        self.stdout.write('    To create contracts, first create supplier contacts and link them')

    def _clear_procurement_data(self):
        """Clear existing procurement data"""
        try:
            PurchaseOrder.objects.all().delete()
            RequestItem.objects.all().delete()
            ProcurementRequest.objects.all().delete()
            Contract.objects.all().delete()
            self.stdout.write('    Cleared existing procurement data')
        except Exception as e:
            self.stdout.write(f'    Warning: Error clearing procurement data: {e}')
