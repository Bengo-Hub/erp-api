import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model

from business.models import Bussiness, Branch, ProductSettings
from ecommerce.product.models import Category, ProductBrands, Products
from ecommerce.stockinventory.models import StockInventory, Unit

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with demo product data linked to Codevertex IT Solutions business'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=20, help='Number of products to generate')
        parser.add_argument('--minimal', action='store_true', help='Seed a minimal number of products (1)')

    def handle(self, *args, **options):
        count = options['count']
        minimal = options.get('minimal')

        if minimal:
            count = 1

        # Prefer the standardized single business 'Codevertex IT Solutions'; fallback to first business
        business = Bussiness.objects.filter(name__iexact='Codevertex IT Solutions').first() or Bussiness.objects.first()
        if not business:
            self.stdout.write(self.style.ERROR('No business found. Please run business seeding first.'))
            return

        # Get the single main branch (prefer branch for business)
        business_branch = Branch.objects.filter(business=business, is_main_branch=True).first()
        if not business_branch:
            self.stdout.write(self.style.ERROR('Main branch not found. Please run business seeding first.'))
            return

        # Create product categories (Category model)
        categories = [
            "Electronics", "Fashion", "Home & Kitchen", "Beauty & Personal Care",
            "Sports & Outdoors", "Books", "Toys & Games", "Health & Wellness"
        ]
        category_objects = {}
        for category_name in categories:
            cat, _ = Category.objects.get_or_create(name=category_name, defaults={'status': 'active'})
            category_objects[category_name] = cat

        # Create product brands
        brands = [
            "Techwave", "FashionFusion", "HomeEssentials", "GlowBeauty",
            "ActiveLife", "BookWorm", "PlayTime", "VitalHealth"
        ]
        brand_objects = {}
        for brand_name in brands:
            brand, _ = ProductBrands.objects.get_or_create(title=brand_name)
            brand_objects[brand_name] = brand

        # Ensure default unit exists
        Unit.objects.get_or_create(title='Piece(s)')

        # Ensure ProductSettings exists for the business (required by StockInventory.save())
        ProductSettings.objects.get_or_create(
            business=business,
            defaults={
                'default_unit': 'Piece(s)',
                'enable_warranty': False,
                'enable_product_expiry': False,
                'stop_selling_days_before_expiry': 1,
                'sku_prefix': 'BNG'
            }
        )

        # Generate demo products and corresponding inventory
        with transaction.atomic():
            products_created = 0
            for i in range(count):
                category_name = random.choice(categories)
                brand_name = random.choice(brands)

                product_name = f"{brand_name} {category_name} Product {i+1}"
                sku = f'SKU{i+1:06d}'
                serial = f'SER{i+1:06d}'

                try:
                    product, created = Products.objects.update_or_create(
                        serial=serial,
                        sku=sku,
                        defaults={
                            'category': category_objects[category_name],
                            'brand': brand_objects[brand_name],
                            'title': product_name,
                            'description': f"Demo {category_name.lower()} product from {brand_name}.",
                            'status': 'active',
                            'weight': f"{random.randint(1, 10)} kg",
                            'dimentions': f"{random.randint(10, 100)}x{random.randint(10, 100)}x{random.randint(5, 50)} cm",
                        }
                    )

                    # Assign business and a product type (goods or service)
                    product.business = business
                    product.product_type = random.choice(['goods'] * 8 + ['service'] * 2)

                    buying_price = Decimal(str(round(random.uniform(100, 1000), 2)))
                    selling_price = (buying_price * Decimal('1.3')).quantize(Decimal('0.01'))
                    # Set default price on product (useful for services)
                    product.default_price = selling_price
                    product.save()
                    stock_level = random.randint(5, 100)

                    StockInventory.objects.update_or_create(
                        product=product,
                        branch=business_branch,
                        defaults={
                            'product_type': 'single',
                            'buying_price': buying_price,
                            'selling_price': selling_price,
                            'stock_level': stock_level,
                            'reorder_level': max(2, stock_level // 5),
                            'availability': 'In Stock' if stock_level > 0 else 'Out of Stock',
                            'is_new_arrival': True,
                            'is_top_pick': bool(random.getrandbits(1))
                        }
                    )

                    # Only create stock inventory for tangible goods
                    if product.product_type == 'goods':
                        StockInventory.objects.update_or_create(
                            product=product,
                            branch=business_branch,
                            defaults={
                                'product_type': 'single',
                                'buying_price': buying_price,
                                'selling_price': selling_price,
                                'stock_level': stock_level,
                                'reorder_level': max(2, stock_level // 5),
                                'availability': 'In Stock' if stock_level > 0 else 'Out of Stock',
                                'is_new_arrival': True,
                                'is_top_pick': bool(random.getrandbits(1))
                            }
                        )
                    if created:
                        products_created += 1
                        self.stdout.write(f"Created product: {product_name}")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error creating product {i+1}: {str(e)}"))

            self.stdout.write(self.style.SUCCESS(f"Seeded {products_created} new products (updated others as needed)"))
