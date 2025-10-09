# Import necessary libraries
import random
import time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model

from business.models import *
from ecommerce.product.models import *
from ecommerce.stockinventory.models import *
from manufacturing.models import *
User = get_user_model()

class Command(BaseCommand):
    help = 'Simulates a complete manufacturing workflow from start to finish, including formula creation, production, and profit analysis'

    def add_arguments(self, parser):
        parser.add_argument(
            '--product',
            type=str,
            help='Name of the product to manufacture (if not specified, will create a new one)',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Delay in seconds between simulation steps for better visualization',
        )

    def handle(self, *args, **options):
        product_name = options.get('product')
        delay = options.get('delay')
        
        self.stdout.write(self.style.SUCCESS('Starting manufacturing workflow simulation...'))
        time.sleep(delay)
        
        try:
            with transaction.atomic():
                # Set up prerequisites
                admin_user = self._get_admin_user()
                location = self._get_business_location()
                
                # Step 1: Set up raw materials and product
                self.stdout.write(self.style.SUCCESS('\n=== STEP 1: Setting Up Raw Materials and Product ==='))
                time.sleep(delay)
                
                # Ensure units exist
                kg_unit = self._get_or_create_unit('Kg')
                l_unit = self._get_or_create_unit('L')
                bottles_unit = self._get_or_create_unit('Bottles')
                
                # Set up raw materials
                raw_materials = self._setup_raw_materials(location)
                
                # Set up or find finished product
                finished_product = self._setup_finished_product(product_name, location, bottles_unit)
                finished_product_stock=StockInventory.objects.get(product=finished_product)
                
                # Step 2: Create formula
                self.stdout.write(self.style.SUCCESS('\n=== STEP 2: Creating Manufacturing Formula ==='))
                time.sleep(delay)
                
                formula = self._create_formula(admin_user, finished_product, bottles_unit, raw_materials)
                
                # Step 3: Plan production batch
                self.stdout.write(self.style.SUCCESS('\n=== STEP 3: Planning Production Batch ==='))
                time.sleep(delay)
                
                batch = self._create_batch(admin_user, formula, location)
                
                # Step 4: Check material availability
                self.stdout.write(self.style.SUCCESS('\n=== STEP 4: Checking Material Availability ==='))
                time.sleep(delay)
                
                self._check_material_availability(batch)
                
                # Step 5: Start production
                self.stdout.write(self.style.SUCCESS('\n=== STEP 5: Starting Production Process ==='))
                time.sleep(delay)
                
                self._start_production(batch)
                
                # Step 6: Production in progress
                self.stdout.write(self.style.SUCCESS('\n=== STEP 6: Production in Progress ==='))
                time.sleep(delay * 2)
                
                self._production_progress(batch, admin_user, delay)
                
                # Step 7: Quality check during production
                self.stdout.write(self.style.SUCCESS('\n=== STEP 7: Mid-Production Quality Check ==='))
                time.sleep(delay)
                
                self._mid_production_quality_check(batch, admin_user)
                
                # Step 8: Complete production
                self.stdout.write(self.style.SUCCESS('\n=== STEP 8: Completing Production ==='))
                time.sleep(delay)
                
                self._complete_production(batch)
                
                # Step 9: Final quality check
                self.stdout.write(self.style.SUCCESS('\n=== STEP 9: Final Quality Check ==='))
                time.sleep(delay)
                
                self._final_quality_check(batch, admin_user)
                
                # Step 10: Cost and profit analysis
                self.stdout.write(self.style.SUCCESS('\n=== STEP 10: Cost and Profit Analysis ==='))
                time.sleep(delay)
                
                self._analyze_costs_and_profit(batch, finished_product)
                
                # Step 11: Update analytics
                self.stdout.write(self.style.SUCCESS('\n=== STEP 11: Updating Analytics ==='))
                time.sleep(delay)
                
                self._update_analytics()
                
                self.stdout.write(self.style.SUCCESS('\n=== SIMULATION COMPLETE ==='))
                self.stdout.write(self.style.SUCCESS(f'Successfully simulated entire manufacturing workflow for {finished_product_stock.product.title}'))
                self.stdout.write(self.style.SUCCESS(f'Batch #{batch.batch_number} produced {batch.actual_quantity} units at a unit cost of {batch.get_unit_cost()}'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error during simulation: {e}'))
            raise

    def _get_admin_user(self):
        """Get an admin user for the simulation"""
        admin = User.objects.filter(is_superuser=True).first()
        if not admin:
            admin = User.objects.filter(is_staff=True).first()
        if not admin:
            admin = User.objects.first()
        if not admin:
            admin = User.objects.create_superuser(
                username='admin',
                email='admin@example.com',
                password='admin123'
            )
        self.stdout.write(f'Using user: {admin.username}')
        return admin

    def _get_business_location(self):
        """Get a business location for the simulation"""
        location = BusinessLocation.objects.first()
        if not location:
            location = BusinessLocation.objects.create(
                name='Main Factory',
                code='MF001',
                address='123 Manufacturing St.',
                city='Nairobi',
                postal_code='00100',
                phone_number='+254712345678',
                email='factory@example.com',
                is_active=True
            )
        self.stdout.write(f'Using location: {location.business.name}')
        return location

    def _get_or_create_unit(self, unit_name):
        """Get or create a unit of measurement"""
        unit, created = Unit.objects.get_or_create(title=unit_name)
        if created:
            self.stdout.write(f'Created unit: {unit_name}')
        return unit

    def _setup_raw_materials(self, location):
        """Set up raw materials for the simulation"""
        # Get or create raw materials category
        raw_materials_category, _ = Category.objects.get_or_create(
            name='Raw Materials'
        )
        
        raw_materials_data = [
            {
                'title': 'Simulated Surfactant',
                'description': 'Primary cleaning agent',
                'price': Decimal('450.00'),
                'buying_price': Decimal('450.00'),
                'stock_level': 500,
                'unit': 'Kg'
            },
            {
                'title': 'Simulated Fragrance',
                'description': 'Pleasant scent for detergent',
                'price': Decimal('1200.00'),
                'buying_price': Decimal('1200.00'),
                'stock_level': 100,
                'unit': 'L'
            },
            {
                'title': 'Simulated Water',
                'description': 'Base for liquid detergent',
                'price': Decimal('15.00'),
                'buying_price': Decimal('15.00'),
                'stock_level': 2000,
                'unit': 'L'
            },
            {
                'title': 'Simulated Preservative',
                'description': 'Extends product shelf life',
                'price': Decimal('680.00'),
                'buying_price': Decimal('680.00'),
                'stock_level': 100,
                'unit': 'Kg'
            },
            {
                'title': 'Simulated Colorant',
                'description': 'Adds color to the product',
                'price': Decimal('1500.00'),
                'buying_price': Decimal('1500.00'),
                'stock_level': 50,
                'unit': 'Kg'
            }
        ]
        
        raw_materials = []
        
        for rm_data in raw_materials_data:
            unit_name = rm_data.pop('unit')
            stock_level = rm_data.pop('stock_level')
            
            # Create or get product
            product, _ = Products.objects.get_or_create(
                title=rm_data['title'],
                defaults={
                    'description': rm_data['description'],
                    'category': raw_materials_category
                }
            )
            
            # Create or get inventory item
            unit = Unit.objects.get(title=unit_name)
            stock, _ = StockInventory.objects.get_or_create(
                product=product,
                location=location,
                defaults={
                    'product_type': 'single',
                    'buying_price': rm_data['buying_price'],
                    'selling_price': rm_data['price'],
                    'manufacturing_cost': Decimal('0.00'),
                    'stock_level': stock_level,
                    'reorder_level': stock_level // 5,
                    'unit': unit,
                    'location': location,
                    'availability': 'In Stock'
                }
            )
            
            raw_materials.append(stock)
            self.stdout.write(f'Prepared raw material: {product.title} (Qty: {stock_level} {unit_name})')
        
        return raw_materials

    def _setup_finished_product(self, product_name, location, unit):
        """Set up the finished product for manufacturing"""
        if not product_name:
            product_name = f"Simulated Detergent {timezone.now().strftime('%Y%m%d%H%M')}"
        
        # Get or create detergents category
        detergents_category, _ = Category.objects.get_or_create(name='Detergents')
        
        # Create or get the product
        product, created = Products.objects.get_or_create(
            title=product_name,
            defaults={
                'description': 'Simulation detergent product',
                'category': detergents_category
            }
        )
        
        # Create or get inventory item
        stock, _ = StockInventory.objects.get_or_create(
            product=product,
            location=location,
            defaults={
                'product_type': 'single',
                'buying_price': Decimal('0.00'),  # Will be calculated from manufacturing
                'selling_price': Decimal('200.00'),
                'manufacturing_cost': Decimal('0.00'),  # Will be calculated from production
                'stock_level': 0,  # Starting with zero stock
                'reorder_level': 100,
                'unit': unit,
                'location': location,
                'availability': 'Out of Stock'
            }
        )
        
        if created:
            self.stdout.write(f'Created new product: {product_name}')
        else:
            self.stdout.write(f'Using existing product: {product_name}')
        
        return product

    def _create_formula(self, admin_user, finished_product, output_unit, raw_materials):
        """Create a manufacturing formula for the finished product"""
        formula_name = f"Formula for {finished_product.title}"
        
        # Create the formula
        formula = ProductFormula.objects.create(
            name=formula_name,
            description=f"Standard formula for {finished_product.title}",
            final_product=finished_product,
            expected_output_quantity=Decimal('100'),  # 100 bottles per batch
            output_unit=output_unit,
            is_active=True,
            created_by=admin_user,
            version=1
        )
        
        self.stdout.write(f'Created formula: {formula_name} (v{formula.version})')
        
        # Create formula ingredients
        ingredients = [
            {'raw_material': raw_materials[0], 'quantity': Decimal('5'), 'unit': Unit.objects.get(title='Kg')},  # Surfactant
            {'raw_material': raw_materials[1], 'quantity': Decimal('2'), 'unit': Unit.objects.get(title='L')},   # Fragrance
            {'raw_material': raw_materials[2], 'quantity': Decimal('85'), 'unit': Unit.objects.get(title='L')},  # Water
            {'raw_material': raw_materials[3], 'quantity': Decimal('1.5'), 'unit': Unit.objects.get(title='Kg')}, # Preservative
            {'raw_material': raw_materials[4], 'quantity': Decimal('0.5'), 'unit': Unit.objects.get(title='Kg')}, # Colorant
        ]
        
        for ingredient_data in ingredients:
            ingredient = FormulaIngredient.objects.create(
                formula=formula,
                **ingredient_data
            )
            self.stdout.write(f'Added ingredient: {ingredient.raw_material.product.title} - {ingredient.quantity} {ingredient.unit.title}')
        
        # Calculate and display raw material cost
        raw_material_cost = formula.get_raw_material_cost()
        suggested_price = formula.get_suggested_selling_price()
        
        self.stdout.write(f'Formula raw material cost: {raw_material_cost} for {formula.expected_output_quantity} units')
        self.stdout.write(f'Cost per unit: {raw_material_cost / formula.expected_output_quantity}')
        self.stdout.write(f'Suggested selling price: {suggested_price} per unit (30% markup)')
        
        # Update the finished product's selling price based on formula
        finished_product.selling_price = suggested_price
        finished_product.save()
        
        return formula

    def _create_batch(self, admin_user, formula, location):
        """Create a production batch based on the formula"""
        # Schedule for today
        scheduled_date = timezone.now() + timezone.timedelta(hours=1)
        
        # Create the batch
        batch = ProductionBatch.objects.create(
            formula=formula,
            location=location,
            scheduled_date=scheduled_date,
            status='planned',
            planned_quantity=formula.expected_output_quantity,
            notes='Simulation batch for demonstration',
            created_by=admin_user,
            supervisor=admin_user
        )
        
        self.stdout.write(f'Created production batch: {batch.batch_number}')
        self.stdout.write(f'Scheduled for: {scheduled_date}')
        self.stdout.write(f'Planned quantity: {batch.planned_quantity} {formula.output_unit.title}')
        
        return batch

    def _check_material_availability(self, batch):
        """Check if all required materials are available"""
        missing_materials = batch.check_material_availability()
        
        if missing_materials:
            self.stdout.write(self.style.WARNING('Material availability check: SOME MATERIALS ARE LOW'))
            for material in missing_materials:
                self.stdout.write(self.style.WARNING(
                    f"  - {material['material'].product.title}: "
                    f"Required {material['required']}, Available {material['available']}, "
                    f"Shortage {material['shortage']}"
                ))
        else:
            self.stdout.write(self.style.SUCCESS('Material availability check: ALL MATERIALS AVAILABLE'))
            
        # List all required materials
        formula = batch.formula
        batch_ratio = batch.planned_quantity / formula.expected_output_quantity
        
        self.stdout.write('Raw materials needed for this batch:')
        for ingredient in formula.ingredients.all():
            required_quantity = ingredient.quantity * batch_ratio
            available = ingredient.raw_material.stock_level
            
            self.stdout.write(f"  - {ingredient.raw_material.product.title}: "
                            f"Need {required_quantity} {ingredient.unit.title}, "
                            f"Available {available} {ingredient.raw_material.unit.title}")

    def _start_production(self, batch):
        """Start the production process"""
        try:
            batch.start_production()
            self.stdout.write(self.style.SUCCESS(f'Production started for batch {batch.batch_number}'))
            self.stdout.write(f'Start time: {batch.start_date}')
            
            # List reserved materials
            self.stdout.write('Raw materials reserved for this batch:')
            for material in batch.raw_materials.all():
                self.stdout.write(f"  - {material.raw_material.product.title}: "
                                f"{material.planned_quantity} {material.unit.title}")
                
            # Check inventory levels after reservation
            self.stdout.write('Updated inventory levels after materials reservation:')
            for material in batch.raw_materials.all():
                self.stdout.write(f"  - {material.raw_material.product.title}: "
                                f"Remaining stock: {material.raw_material.stock_level} {material.raw_material.unit.title}")
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f'Failed to start production: {e}'))
            raise

    def _production_progress(self, batch, admin_user, delay):
        """Simulate production progress updates"""
        steps = [
            "Mixing raw materials...",
            "Heating mixture to required temperature...",
            "Adding fragrances and colorants...",
            "Stabilizing pH levels...",
            "Cooling mixture...",
            "Preparing for packaging..."
        ]
        
        for i, step in enumerate(steps, 1):
            self.stdout.write(f"Production step {i}/{len(steps)}: {step}")
            time.sleep(delay)
            completion = i / len(steps) * 100
            self.stdout.write(f"Production progress: {completion:.1f}%")

    def _mid_production_quality_check(self, batch, admin_user):
        """Perform a quality check during production"""
        check = QualityCheck.objects.create(
            batch=batch,
            check_date=timezone.now(),
            inspector=admin_user,
            result='pending',
            notes='Mid-production quality check: pH and consistency tested.'
        )
        
        self.stdout.write(f'Mid-production quality check performed by {check.inspector.username}')
        self.stdout.write(f'Check time: {check.check_date}')
        self.stdout.write(f'Status: {check.result}')
        self.stdout.write(f'Notes: {check.notes}')

    def _complete_production(self, batch):
        """Complete the production process"""
        # Slightly adjust actual quantity from planned (simulating real-world variance)
        variance_factor = Decimal(str(random.uniform(0.95, 1.05))).quantize(Decimal('0.01'))
        actual_quantity = (batch.planned_quantity * variance_factor).quantize(Decimal('0.01'))
        
        # Set actual quantities for materials
        for material in batch.raw_materials.all():
            material.actual_quantity = material.planned_quantity
            material.save()
        
        # Complete the batch
        batch.status = 'completed'
        batch.end_date = timezone.now()
        batch.actual_quantity = actual_quantity
        batch.save()
        
        # Update the final product inventory
        finished_product = batch.formula.final_product
        finished_product_stock=StockInventory.objects.get(product=finished_product)
        finished_product_stock.stock_level += actual_quantity
        if finished_product_stock.stock_level > 0:
            finished_product_stock.availability = 'In Stock'
        finished_product_stock.save()
        
        self.stdout.write(self.style.SUCCESS(f'Production completed for batch {batch.batch_number}'))
        self.stdout.write(f'Completion time: {batch.end_date}')
        self.stdout.write(f'Planned quantity: {batch.planned_quantity}')
        self.stdout.write(f'Actual quantity: {batch.actual_quantity}')
        self.stdout.write(f'Efficiency rate: {(batch.actual_quantity / batch.planned_quantity * 100):.1f}%')
        
        # Check finished product inventory
        final_product = batch.formula.final_product
        self.stdout.write(f'Updated finished product inventory:')
        self.stdout.write(f'  - {final_product.title}: {finished_product_stock.stock_level} {finished_product_stock.unit.title}')

    def _final_quality_check(self, batch, admin_user):
        """Perform the final quality check"""
        check = QualityCheck.objects.create(
            batch=batch,
            check_date=timezone.now(),
            inspector=admin_user,
            result='pass',
            notes='Final quality check: Product meets all standards for color, scent, pH, and cleaning effectiveness.'
        )
        
        self.stdout.write(self.style.SUCCESS(f'Final quality check: {check.result.upper()}'))
        self.stdout.write(f'Check time: {check.check_date}')
        self.stdout.write(f'Inspector: {check.inspector.username}')
        self.stdout.write(f'Notes: {check.notes}')

    def _analyze_costs_and_profit(self, batch, finished_product):
        """Analyze production costs and potential profit"""
        # Analyze costs
        raw_material_cost = batch.get_raw_material_cost()
        total_cost = batch.get_total_cost()
        unit_cost = batch.get_unit_cost()
        
        # Create RawMaterialUsage records for tracking
        for material in batch.raw_materials.all():
            RawMaterialUsage.objects.create(
                finished_product=finished_product,
                raw_material=material.raw_material,
                quantity_used=material.actual_quantity,
                transaction_type='production',
                notes=f'Used in batch {batch.batch_number}'
            )
        
        # Set a selling price with margin
        margin_percentage = 30
        calculated_selling_price = unit_cost * (1 + Decimal(margin_percentage) / 100)
        
        # Update the finished product
        finished_product_stock = StockInventory.objects.get(product=finished_product)
        current_selling_price = finished_product_stock.selling_price
        
        # Update the manufacturing cost in the inventory
        finished_product_stock.manufacturing_cost = unit_cost
        # Calculate profit margin
        finished_product_stock.profit_margin = current_selling_price - unit_cost
        finished_product_stock.save()
        
        self.stdout.write(f'Production Costs:')
        self.stdout.write(f'  - Raw Materials: {raw_material_cost}')
        self.stdout.write(f'  - Labor: {batch.labor_cost}')
        self.stdout.write(f'  - Overhead: {batch.overhead_cost}')
        self.stdout.write(f'  - Total Cost: {total_cost}')
        self.stdout.write(f'  - Unit Cost: {unit_cost} per {finished_product_stock.unit.title}')
        
        self.stdout.write(f'\nPricing Analysis:')
        self.stdout.write(f'  - Calculated selling price ({margin_percentage}% margin): {calculated_selling_price}')
        self.stdout.write(f'  - Current selling price: {current_selling_price}')
        
        potential_profit_per_unit = current_selling_price - unit_cost
        potential_profit_margin = (potential_profit_per_unit / current_selling_price * 100).quantize(Decimal('0.1'))
        potential_batch_profit = potential_profit_per_unit * batch.actual_quantity
        
        self.stdout.write(f'\nProfit Analysis:')
        self.stdout.write(f'  - Profit per unit: {potential_profit_per_unit}')
        self.stdout.write(f'  - Profit margin: {potential_profit_margin}%')
        self.stdout.write(f'  - Total batch profit: {potential_batch_profit}')
        
        # Log the profit metrics
        self.stdout.write(self.style.SUCCESS(f'Updated manufacturing cost for {finished_product_stock.product.title}: {unit_cost}'))
        self.stdout.write(self.style.SUCCESS(f'Updated profit margin for {finished_product_stock.product.title}: {finished_product_stock.profit_margin}'))
        


    def _update_analytics(self):
        """Update manufacturing analytics"""
        # Update for today
        today = timezone.now().date()
        analytics = ManufacturingAnalytics.update_for_date(today)
        
        self.stdout.write(f'Updated manufacturing analytics for {today}:')
        self.stdout.write(f'  - Total batches: {analytics.total_batches}')
        self.stdout.write(f'  - Completed batches: {analytics.completed_batches}')
        self.stdout.write(f'  - Total production quantity: {analytics.total_production_quantity}')
        self.stdout.write(f'  - Total raw material cost: {analytics.total_raw_material_cost}')
        self.stdout.write(f'  - Total labor cost: {analytics.total_labor_cost}')
        self.stdout.write(f'  - Total overhead cost: {analytics.total_overhead_cost}')
