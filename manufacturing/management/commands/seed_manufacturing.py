import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone

from business.models import Bussiness, BusinessLocation, ProductSettings, Branch
from ecommerce.product.models import Products, Category
from ecommerce.stockinventory.models import StockInventory, Unit
from manufacturing.models import (
    ProductFormula, FormulaIngredient, ProductionBatch, 
    BatchRawMaterial, QualityCheck, ManufacturingAnalytics, RawMaterialUsage
)

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the manufacturing module with realistic data for a detergent manufacturing workflow'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing manufacturing data before seeding',
        )
        parser.add_argument(
            '--full',
            action='store_true',
            help='Seed products and raw materials in addition to manufacturing data',
        )
        parser.add_argument(
            '--simulate',
            action='store_true',
            help='Simulate complete manufacturing workflow with batch production',
        )
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Seed a minimal manufacturing dataset (small counts and 1-2 items)',
        )

    def handle(self, *args, **options):
        clear_data = options['clear']
        full_seeding = options['full']
        simulate = options['simulate']
        minimal = options.get('minimal')
        
        self.stdout.write(self.style.SUCCESS('Starting manufacturing module seeding...'))
        
        # Get or create admin user
        admin_user = self._get_or_create_admin_user()
        
        # Get or create business location
        location = self._get_or_create_business_location()
        
        # Clear data if requested
        if clear_data:
            self._clear_manufacturing_data()
        
        # Create basic units if they don't exist
        self._create_units()
        
        # Ensure ProductSettings exists for the business (required by StockInventory.save())
        # Get the first business that uses this location
        business = Bussiness.objects.filter(location=location).first()
        if business:
            ProductSettings.objects.get_or_create(
                business=business,
                defaults={
                    'default_unit': 'Kg',
                    'enable_warranty': False,
                    'enable_product_expiry': False,
                    'stop_selling_days_before_expiry': 1,
                    'sku_prefix': 'MFG'
                }
            )
        
        # Create products and raw materials if full seeding is requested
        if full_seeding:
            # In minimal mode create a reduced set of products/raw materials
            if minimal:
                self._create_products_and_raw_materials(location, minimal=True)
            else:
                self._create_products_and_raw_materials(location)
        
        # Create manufacturing formulas
        formulas = self._create_formulas(admin_user)
        
        # Create production batches
        # Prefer the standardized single business 'Codevertex IT Solutions'; fall back to the first available business
        business = Bussiness.objects.filter(name__iexact='Codevertex IT Solutions').first() or Bussiness.objects.first()
        if not business:
            self.stdout.write(self.style.ERROR('No business found. Please run business seeding first.'))
            return
        
        branch = Branch.objects.filter(business=business, is_main_branch=True).first()
        if not branch:
            self.stdout.write(self.style.ERROR('Main branch not found. Please run business seeding first.'))
            return
        
        batches = self._create_production_batches(admin_user, branch, formulas, minimal=minimal)
        
        # Simulate workflow if requested
        if simulate:
            self._simulate_workflows(batches, admin_user)
            
        # Generate analytics
        self._generate_analytics()
        
        self.stdout.write(self.style.SUCCESS('Manufacturing module seeding completed successfully!'))

    def _get_or_create_admin_user(self):
        """Get or create an admin user"""
        try:
            admin = User.objects.filter(is_superuser=True).first()
            if not admin:
                admin = User.objects.create_superuser(
                    username='admin',
                    email='admin@example.com',
                    password='admin123'
                )
                self.stdout.write(self.style.SUCCESS('Admin user created'))
            return admin
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating admin user: {e}'))
            return User.objects.first()  # Fallback to any available user

    def _get_or_create_business_location(self):
        """Get the existing business location for the canonical Codevertex business."""
        try:
            # Prefer the standardized single business 'Codevertex IT Solutions'; fallback to the first business
            business = Bussiness.objects.filter(name__iexact='Codevertex IT Solutions').first() or Bussiness.objects.first()
            if not business:
                self.stdout.write(self.style.ERROR('No business found. Please run business seeding first.'))
                return None
            
            # Get the business location
            location = business.location
            if not location:
                self.stdout.write(self.style.ERROR('Business location not found. Please run business seeding first.'))
                return None
            
            self.stdout.write(self.style.SUCCESS(f'Using existing business location: {location.city}'))
            
            # Ensure ProductSettings exists for the business (required by StockInventory.save())
            ProductSettings.objects.get_or_create(
                business=business,
                defaults={
                    'default_unit': 'Kg',
                    'enable_warranty': False,
                    'enable_product_expiry': False,
                    'stop_selling_days_before_expiry': 1,
                    'sku_prefix': 'MF'
                }
            )
            
            return location
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error getting business location: {e}'))
            return None

    def _clear_manufacturing_data(self):
        """Clear existing manufacturing data"""
        try:
            with transaction.atomic():
                ManufacturingAnalytics.objects.all().delete()
                QualityCheck.objects.all().delete()
                BatchRawMaterial.objects.all().delete()
                ProductionBatch.objects.all().delete()
                FormulaIngredient.objects.all().delete()
                ProductFormula.objects.all().delete()
                RawMaterialUsage.objects.all().delete()
                self.stdout.write(self.style.SUCCESS('Existing manufacturing data cleared'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error clearing manufacturing data: {e}'))

    def _create_units(self):
        """Create basic units for measurements"""
        units = [
            'Kg', 'g', 'L', 'ml', 'Pieces', 'Bottles', 'Bars', 'Packs'
        ]
        
        created_count = 0
        for unit_name in units:
            _, created = Unit.objects.get_or_create(title=unit_name)
            if created:
                created_count += 1
        
        if created_count > 0:
            self.stdout.write(self.style.SUCCESS(f'Created {created_count} measurement units'))
        else:
            self.stdout.write(self.style.SUCCESS('All measurement units already exist'))

    def _create_products_and_raw_materials(self, location, minimal=False):
        """Create products and raw materials"""
        # Create categories (Category model)
        root_raw, _ = Category.objects.get_or_create(name='Raw Materials', defaults={'status': 'active'})
        root_finished, _ = Category.objects.get_or_create(name='Finished Goods', defaults={'status': 'active'})
        
        # Raw Materials
        raw_materials = [
            {
                'title': 'Sodium Lauryl Sulfate',
                'description': 'Foaming agent for detergents',
                'category': root_raw,
                'stock_level': 1000,
                'reorder_level': 200,
                'unit': 'Kg'
            },
            {
                'title': 'Sodium Hydroxide',
                'description': 'Used in soap making',
                'category': root_raw,
                'stock_level': 500,
                'reorder_level': 100,
                'unit': 'Kg'
            },
            {
                'title': 'Citric Acid',
                'description': 'pH adjuster for detergents',
                'category': root_raw,
                'stock_level': 300,
                'reorder_level': 50,
                'unit': 'Kg'
            },
            {
                'title': 'Fragrance Oil - Lavender',
                'description': 'Lavender scent for detergents',
                'category': root_raw,
                'stock_level': 100,
                'reorder_level': 20,
                'unit': 'L'
            },
            {
                'title': 'Fragrance Oil - Lemon',
                'description': 'Lemon scent for detergents',
                'category': root_raw,
                'stock_level': 100,
                'reorder_level': 20,
                'unit': 'L'
            },
            {
                'title': 'Purified Water',
                'description': 'Base for liquid detergents',
                'category': root_raw,
                'stock_level': 5000,
                'reorder_level': 1000,
                'unit': 'L'
            },
            {
                'title': 'Coconut Oil',
                'description': 'Base oil for soap making',
                'category': root_raw,
                'stock_level': 400,
                'reorder_level': 100,
                'unit': 'L'
            },
            {
                'title': 'Palm Oil',
                'description': 'Base oil for soap making',
                'category': root_raw,
                'stock_level': 350,
                'reorder_level': 80,
                'unit': 'L'
            },
            {
                'title': 'Glycerin',
                'description': 'Moisturizing agent for soaps',
                'category': root_raw,
                'stock_level': 200,
                'reorder_level': 50,
                'unit': 'L'
            },
            {
                'title': 'Sodium Carbonate',
                'description': 'Builder for detergent powders',
                'category': root_raw,
                'stock_level': 600,
                'reorder_level': 150,
                'unit': 'Kg'
            }
        ]
        
        # Finished Products
        finished_products = [
            {
                'title': 'Liquid Detergent 1L',
                'description': 'Standard liquid detergent for laundry',
                'category': root_finished,
                'stock_level': 200,
                'reorder_level': 50,
                'unit': 'Bottles'
            },
            {
                'title': 'Premium Bar Soap 100g',
                'description': 'Premium quality bar soap',
                'category': root_finished,
                'stock_level': 500,
                'reorder_level': 100,
                'unit': 'Bars'
            },
            {
                'title': 'Economy Bar Soap 100g',
                'description': 'Budget-friendly bar soap',
                'category': root_finished,
                'stock_level': 600,
                'reorder_level': 120,
                'unit': 'Bars'
            },
            {
                'title': 'Multipurpose Cleaner 500ml',
                'description': 'All-purpose home cleaning solution',
                'category': root_finished,
                'stock_level': 300,
                'reorder_level': 60,
                'unit': 'Bottles'
            },
            {
                'title': 'Dish Soap 750ml',
                'description': 'Concentrated dish washing liquid',
                'category': root_finished,
                'stock_level': 250,
                'reorder_level': 50,
                'unit': 'Bottles'
            }
        ]
        
        if minimal:
            # Keep only the first item of each type for minimal mode
            self._create_products_with_inventory(raw_materials[:1], location)
            self._create_products_with_inventory(finished_products[:1], location)
            self.stdout.write(self.style.SUCCESS('Minimal mode: created 1 raw material and 1 finished product'))
        else:
            # Create raw materials
            self._create_products_with_inventory(raw_materials, location)
            # Create finished products
            self._create_products_with_inventory(finished_products, location)
        
        # Create finished products
        self._create_products_with_inventory(finished_products, location)
        
        self.stdout.write(self.style.SUCCESS(f'Created {len(raw_materials)} raw materials and {len(finished_products)} finished products'))

    def _create_products_with_inventory(self, products_data, location):
        """Create products and their inventory items"""
        # Prefer the standardized single business 'Codevertex IT Solutions'; fall back to the first business
        business = Bussiness.objects.filter(name__iexact='Codevertex IT Solutions').first() or Bussiness.objects.first()
        if not business:
            self.stdout.write(self.style.ERROR('No business found. Please run business seeding first.'))
            return
        
        branch = Branch.objects.filter(business=business, is_main_branch=True).first()
        if not branch:
            self.stdout.write(self.style.ERROR('Main branch not found. Please run business seeding first.'))
            return
        
        for product_data in products_data:
            unit_title = product_data.pop('unit')
            stock_level = product_data.pop('stock_level')
            reorder_level = product_data.pop('reorder_level')
            
            # Create or get the product
            product, created = Products.objects.get_or_create(
                title=product_data['title'],
                defaults=product_data
            )
            
            if not created:
                # Update existing product
                for key, value in product_data.items():
                    setattr(product, key, value)
                product.save()
            
            # Create or update inventory with pricing
            unit = Unit.objects.get(title=unit_title)
            
            # Generate realistic pricing based on product type
            if 'Raw Materials' in str(product_data['category']):
                # Raw materials have lower prices
                buying_price = Decimal(str(round(random.uniform(50, 1500), 2)))
            else:
                # Finished products have higher prices
                buying_price = Decimal(str(round(random.uniform(20, 200), 2)))
            
            selling_price = (buying_price * Decimal('1.3')).quantize(Decimal('0.01'))
            
            stock, _ = StockInventory.objects.get_or_create(
                product=product,
                branch=branch,
                defaults={
                    'product_type': 'single',
                    'buying_price': buying_price,
                    'selling_price': selling_price,
                    'stock_level': stock_level,
                    'reorder_level': reorder_level,
                    'unit': unit,
                    'availability': 'In Stock' if stock_level > 0 else 'Out of Stock'
                }
            )
            
            # Update inventory if it already existed
            if _:
                stock.buying_price = buying_price
                stock.selling_price = selling_price
                stock.stock_level = stock_level
                stock.reorder_level = reorder_level
                stock.unit = unit
                stock.availability = 'In Stock' if stock_level > 0 else 'Out of Stock'
                stock.save()

    def _create_formulas(self, admin_user):
        """Create manufacturing formulas with ingredients"""
        # Check if required products exist
        required_products = [
            'Sodium Lauryl Sulfate', 'Sodium Hydroxide', 'Citric Acid',
            'Fragrance Oil - Lavender', 'Fragrance Oil - Lemon', 'Purified Water',
            'Coconut Oil', 'Palm Oil', 'Glycerin', 'Sodium Carbonate',
            'Liquid Detergent 1L', 'Premium Bar Soap 100g', 'Economy Bar Soap 100g',
            'Multipurpose Cleaner 500ml', 'Dish Soap 750ml'
        ]
        for title in required_products:
            if not StockInventory.objects.filter(product__title=title).exists():
                self.stdout.write(self.style.WARNING(f'Required product "{title}" not found. Skipping manufacturing formulas.'))
                return []
        
        # Get units
        kg_unit = Unit.objects.get(title='Kg')
        l_unit = Unit.objects.get(title='L')
        bottles_unit = Unit.objects.get(title='Bottles')
        bars_unit = Unit.objects.get(title='Bars')
        
        # Get products
        # Raw materials (as StockInventory for ingredients)
        sls = StockInventory.objects.get(product__title='Sodium Lauryl Sulfate')
        naoh = StockInventory.objects.get(product__title='Sodium Hydroxide')
        citric_acid = StockInventory.objects.get(product__title='Citric Acid')
        fragrance_lavender = StockInventory.objects.get(product__title='Fragrance Oil - Lavender')
        fragrance_lemon = StockInventory.objects.get(product__title='Fragrance Oil - Lemon')
        water = StockInventory.objects.get(product__title='Purified Water')
        coconut_oil = StockInventory.objects.get(product__title='Coconut Oil')
        palm_oil = StockInventory.objects.get(product__title='Palm Oil')
        glycerin = StockInventory.objects.get(product__title='Glycerin')
        soda_ash = StockInventory.objects.get(product__title='Sodium Carbonate')
        
        # Finished product Stocks and their Product instances
        liquid_detergent_stock = StockInventory.objects.get(product__title='Liquid Detergent 1L')
        premium_soap_stock = StockInventory.objects.get(product__title='Premium Bar Soap 100g')
        economy_soap_stock = StockInventory.objects.get(product__title='Economy Bar Soap 100g')
        multipurpose_stock = StockInventory.objects.get(product__title='Multipurpose Cleaner 500ml')
        dish_soap_stock = StockInventory.objects.get(product__title='Dish Soap 750ml')

        liquid_detergent = liquid_detergent_stock.product
        premium_soap = premium_soap_stock.product
        economy_soap = economy_soap_stock.product
        multipurpose = multipurpose_stock.product
        dish_soap = dish_soap_stock.product
        
        # Create formulas with ingredients
        formulas_data = [
            {
                'name': 'Liquid Detergent Standard',
                'description': 'Standard formula for liquid laundry detergent',
                'final_product': liquid_detergent,
                'expected_output_quantity': Decimal('100'),
                'output_unit': bottles_unit,
                'ingredients': [
                    {'raw_material': sls, 'quantity': Decimal('5'), 'unit': kg_unit},
                    {'raw_material': naoh, 'quantity': Decimal('2'), 'unit': kg_unit},
                    {'raw_material': citric_acid, 'quantity': Decimal('1.5'), 'unit': kg_unit},
                    {'raw_material': fragrance_lavender, 'quantity': Decimal('0.8'), 'unit': l_unit},
                    {'raw_material': water, 'quantity': Decimal('90'), 'unit': l_unit}
                ]
            },
            {
                'name': 'Premium Bar Soap',
                'description': 'Premium quality bar soap formula with moisturizing agents',
                'final_product': premium_soap,
                'expected_output_quantity': Decimal('1000'),
                'output_unit': bars_unit,
                'ingredients': [
                    {'raw_material': naoh, 'quantity': Decimal('12'), 'unit': kg_unit},
                    {'raw_material': coconut_oil, 'quantity': Decimal('30'), 'unit': l_unit},
                    {'raw_material': palm_oil, 'quantity': Decimal('25'), 'unit': l_unit},
                    {'raw_material': glycerin, 'quantity': Decimal('10'), 'unit': l_unit},
                    {'raw_material': fragrance_lavender, 'quantity': Decimal('2'), 'unit': l_unit},
                    {'raw_material': water, 'quantity': Decimal('20'), 'unit': l_unit}
                ]
            },
            {
                'name': 'Economy Bar Soap',
                'description': 'Cost-effective bar soap formula',
                'final_product': economy_soap,
                'expected_output_quantity': Decimal('1000'),
                'output_unit': bars_unit,
                'ingredients': [
                    {'raw_material': naoh, 'quantity': Decimal('12'), 'unit': kg_unit},
                    {'raw_material': palm_oil, 'quantity': Decimal('45'), 'unit': l_unit},
                    {'raw_material': soda_ash, 'quantity': Decimal('8'), 'unit': kg_unit},
                    {'raw_material': fragrance_lemon, 'quantity': Decimal('1.5'), 'unit': l_unit},
                    {'raw_material': water, 'quantity': Decimal('25'), 'unit': l_unit}
                ]
            },
            {
                'name': 'Multipurpose Cleaner',
                'description': 'All-purpose cleaning solution formula',
                'final_product': multipurpose,
                'expected_output_quantity': Decimal('200'),
                'output_unit': bottles_unit,
                'ingredients': [
                    {'raw_material': sls, 'quantity': Decimal('3'), 'unit': kg_unit},
                    {'raw_material': citric_acid, 'quantity': Decimal('2'), 'unit': kg_unit},
                    {'raw_material': soda_ash, 'quantity': Decimal('1'), 'unit': kg_unit},
                    {'raw_material': fragrance_lemon, 'quantity': Decimal('1.2'), 'unit': l_unit},
                    {'raw_material': water, 'quantity': Decimal('95'), 'unit': l_unit}
                ]
            },
            {
                'name': 'Dish Washing Liquid',
                'description': 'Concentrated dish soap formula',
                'final_product': dish_soap,
                'expected_output_quantity': Decimal('150'),
                'output_unit': bottles_unit,
                'ingredients': [
                    {'raw_material': sls, 'quantity': Decimal('8'), 'unit': kg_unit},
                    {'raw_material': citric_acid, 'quantity': Decimal('1'), 'unit': kg_unit},
                    {'raw_material': glycerin, 'quantity': Decimal('3'), 'unit': l_unit},
                    {'raw_material': fragrance_lemon, 'quantity': Decimal('1.5'), 'unit': l_unit},
                    {'raw_material': water, 'quantity': Decimal('85'), 'unit': l_unit}
                ]
            }
        ]
        
        created_formulas = []
        
        for formula_data in formulas_data:
            ingredients = formula_data.pop('ingredients')
            
            # Create formula
            formula = ProductFormula.objects.create(
                **formula_data,
                is_active=True,
                created_by=admin_user
            )
            
            # Add ingredients
            for ingredient_data in ingredients:
                FormulaIngredient.objects.create(
                    formula=formula,
                    **ingredient_data
                )
            
            created_formulas.append(formula)
            
        self.stdout.write(self.style.SUCCESS(f'Created {len(created_formulas)} manufacturing formulas with ingredients'))
        
        return created_formulas

    def _create_production_batches(self, admin_user, branch, formulas, minimal=False):
        """Create production batches based on formulas"""
        # Create batches with different statuses
        now = timezone.now()
        
        # Statuses and their count
        if minimal:
            status_counts = {
                'planned': 1,
                'in_progress': 0,
                'completed': 1,
                'cancelled': 0,
                'failed': 0
            }
        else:
            status_counts = {
                'planned': 3,
                'in_progress': 2,
                'completed': 5,
                'cancelled': 1,
                'failed': 1
            }
        
        all_batches = []
        
        for status, count in status_counts.items():
            for i in range(count):
                # Select a random formula
                formula = random.choice(formulas)
                
                # Calculate schedule date based on status
                if status in ['completed', 'failed', 'cancelled']:
                    # Past date for completed/failed/cancelled batches
                    days_ago = random.randint(1, 30)
                    scheduled_date = now - timedelta(days=days_ago)
                    start_date = scheduled_date + timedelta(hours=random.randint(1, 3))
                    end_date = start_date + timedelta(hours=random.randint(4, 8)) if status == 'completed' else None
                elif status == 'in_progress':
                    # Recent date for in-progress batches
                    days_ago = random.randint(0, 2)
                    scheduled_date = now - timedelta(days=days_ago)
                    start_date = scheduled_date + timedelta(hours=random.randint(1, 3))
                    end_date = None
                else:  # planned
                    # Future date for planned batches
                    days_ahead = random.randint(1, 10)
                    scheduled_date = now + timedelta(days=days_ahead)
                    start_date = None
                    end_date = None
                
                # Determine quantities
                planned_quantity = formula.expected_output_quantity * Decimal(str(random.uniform(0.5, 2.0))).quantize(Decimal('0.01'))
                actual_quantity = None
                
                if status == 'completed':
                    # For completed batches, actual qty is slightly different from planned
                    variance_factor = Decimal(str(random.uniform(0.90, 1.05))).quantize(Decimal('0.01'))
                    actual_quantity = (planned_quantity * variance_factor).quantize(Decimal('0.01'))
                
                # Create the batch using the provided branch parameter
                batch = ProductionBatch.objects.create(
                    formula=formula,
                    branch=branch,
                    scheduled_date=scheduled_date,
                    start_date=start_date,
                    end_date=end_date,
                    status=status,
                    planned_quantity=planned_quantity,
                    actual_quantity=actual_quantity,
                    labor_cost=Decimal(str(random.uniform(1000, 5000))).quantize(Decimal('0.01')) if status == 'completed' else Decimal('0'),
                    overhead_cost=Decimal(str(random.uniform(500, 2000))).quantize(Decimal('0.01')) if status == 'completed' else Decimal('0'),
                    notes=f'Test batch for {formula.name}',
                    created_by=admin_user,
                    supervisor=admin_user
                )
                
                all_batches.append(batch)
                
                # For completed/in-progress batches, create batch materials
                if status in ['completed', 'in_progress']:
                    self._create_batch_materials(batch)
                
                # For completed/failed batches, create quality checks
                if status in ['completed', 'failed']:
                    result = 'pass' if status == 'completed' else 'fail'
                    self._create_quality_check(batch, admin_user, result)
        
        self.stdout.write(self.style.SUCCESS(f'Created {len(all_batches)} production batches with different statuses'))
        
        return all_batches

    def _create_batch_materials(self, batch):
        """Create batch raw materials for a production batch"""
        formula = batch.formula
        batch_ratio = batch.planned_quantity / formula.expected_output_quantity
        
        for ingredient in formula.ingredients.all():
            required_quantity = ingredient.quantity * batch_ratio
            
            BatchRawMaterial.objects.create(
                batch=batch,
                raw_material=ingredient.raw_material,
                planned_quantity=required_quantity,
                actual_quantity=required_quantity if batch.status == 'completed' else None,
                unit=ingredient.unit,
                cost=ingredient.raw_material.buying_price * required_quantity
            )

    def _create_quality_check(self, batch, admin_user, result='pass'):
        """Create a quality check for a batch"""
        check_date = batch.end_date or timezone.now()
        
        notes = ''
        if result == 'pass':
            notes = 'Product meets all quality standards.'
        else:
            notes = 'Product failed quality check due to inconsistent mixture.'
        
        QualityCheck.objects.create(
            batch=batch,
            check_date=check_date,
            inspector=admin_user,
            result=result,
            notes=notes
        )

    def _simulate_workflows(self, batches, admin_user):
        """Simulate complete workflows by progressing batches through stages"""
        # Select some planned batches to start
        planned_batches = [b for b in batches if b.status == 'planned']
        to_start = planned_batches[:1]  # Start 1 planned batch
        
        # Select some in-progress batches to complete
        in_progress_batches = [b for b in batches if b.status == 'in_progress']
        to_complete = in_progress_batches[:1]  # Complete 1 in-progress batch
        
        # Start planned batches
        for batch in to_start:
            self.stdout.write(f'Starting batch {batch.batch_number}...')
            batch.start_production()
            QualityCheck.objects.create(
                batch=batch,
                check_date=timezone.now(),
                inspector=admin_user,
                result='pending',
                notes='Initial quality check during production start.'
            )
        
        # Complete in-progress batches
        for batch in to_complete:
            self.stdout.write(f'Completing batch {batch.batch_number}...')
            formula = batch.formula
            
            # Set actual_quantity to slightly different than planned
            variance_factor = Decimal(str(random.uniform(0.95, 1.02))).quantize(Decimal('0.01'))
            actual_quantity = (batch.planned_quantity * variance_factor).quantize(Decimal('0.01'))
            
            # Update batch materials with actual quantities
            for material in batch.raw_materials.all():
                material.actual_quantity = material.planned_quantity
                material.save()
            
            # Complete the batch
            batch.complete_production(actual_quantity)
            
            # Create a passing quality check
            QualityCheck.objects.create(
                batch=batch,
                check_date=timezone.now(),
                inspector=admin_user,
                result='pass',
                notes='Final quality check after production. Product meets all standards.'
            )
            
            # Update finished product stock level and manufacturing cost
            final_product = formula.final_product
            final_product.manufacturing_cost = batch.get_unit_cost()
            final_product.save()
            
            # Create raw material usages
            for material in batch.raw_materials.all():
                RawMaterialUsage.objects.create(
                    finished_product=final_product,
                    raw_material=material.raw_material,
                    quantity_used=material.actual_quantity,
                    transaction_type='production',
                    notes=f'Used in Batch #{batch.batch_number}'
                )

    def _generate_analytics(self):
        """Generate manufacturing analytics for recent dates"""
        # Generate analytics for the past 30 days
        now = timezone.now().date()
        start_date = now - timedelta(days=30)
        
        for i in range(31):  # 0 to 30 days
            date = start_date + timedelta(days=i)
            ManufacturingAnalytics.update_for_date(date)
        
        self.stdout.write(self.style.SUCCESS(f'Generated manufacturing analytics for the past 30 days'))
