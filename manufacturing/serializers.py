from rest_framework import serializers
from .models import (
    ProductFormula, FormulaIngredient, ProductionBatch, 
    BatchRawMaterial, QualityCheck, ManufacturingAnalytics
)
from ecommerce.stockinventory.serializers import *
from ecommerce.stockinventory.models import *
from ecommerce.product.serializers import ImagesSerializer

class FinalProductSerializer(serializers.ModelSerializer):
    images=ImagesSerializer(many=True)
    buying_price = serializers.SerializerMethodField()
    class Meta:
        model = Products
        fields = ['id', 'title','buying_price', 'description', 'status','images']
        read_only_fields = ['id']

    def get_buying_price(self, obj):
        # get stock inventory for the product
        stock_inventory = StockInventory.objects.filter(product=obj).first()
        if stock_inventory:
            # get the buying price from the stock inventory
            return stock_inventory.buying_price
        return 0
        
class RawMaterialProductSerializer(serializers.ModelSerializer):
    images=ImagesSerializer(many=True)
    buying_price = serializers.SerializerMethodField()
    class Meta:
        model = Products
        fields = ['id', 'title','buying_price', 'description', 'status','images']
        read_only_fields = ['id']

    def get_buying_price(self, obj):
        # get stock inventory for the product
        stock_inventory = StockInventory.objects.filter(product=obj).first()
        return stock_inventory.buying_price if stock_inventory else 0
    
class FormulaIngredientSerializer(serializers.ModelSerializer):
    raw_material_details = StockSerializer(source='raw_material', read_only=True)
    unit_details = UnitSerializer(source='unit', read_only=True)
    
    class Meta:
        model = FormulaIngredient
        fields = [
            'id', 'raw_material', 'raw_material_details', 
            'quantity', 'unit', 'unit_details', 'notes'
        ]
        read_only_fields = ['id']


# serializers.py

class ProductFormulaSerializer(serializers.ModelSerializer):
    ingredients = FormulaIngredientSerializer(many=True, required=False)
    final_product_details = ProductsSerializer(source='final_product', read_only=True)
    output_unit_details = UnitSerializer(source='output_unit', read_only=True)
    raw_material_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, 
        read_only=True, source='get_raw_material_cost'
    )
    suggested_selling_price = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductFormula
        fields = [
            'id', 'name', 'description', 'final_product', 'final_product_details',
            'expected_output_quantity', 'output_unit', 'output_unit_details',
            'is_active', 'created_by', 'created_at', 'updated_at', 
            'version', 'ingredients', 'raw_material_cost', 'suggested_selling_price'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at', 'version']
    
    def get_suggested_selling_price(self, obj):
        markup = self.context.get('markup_percentage', 30)
        return obj.get_suggested_selling_price(markup_percentage=markup)

    def validate(self, data):
        # Ensure at least one ingredient is provided when creating
        if self.context['request'].method == 'POST' and not data.get('ingredients'):
            raise serializers.ValidationError("At least one ingredient is required")
        return data

    def create(self, validated_data):
        ingredients_data = validated_data.pop('ingredients', [])
        final_product = validated_data.pop('final_product', None)
        print("Final Product ID:", final_product)
        if final_product:
            validated_data['final_product'] = final_product
        user = self.context['request'].user
        
        # Get the next version number if this is an update
        name = validated_data['name']
        version = 1
        if ProductFormula.objects.filter(name=name).exists():
            version = ProductFormula.objects.filter(name=name).aggregate(
                max_version=models.Max('version')
            )['max_version'] + 1
        
        # Create formula
        formula = ProductFormula.objects.create(
            **validated_data,
            created_by=user,
            version=version
        )
        
        # Create ingredients
        for ingredient_data in ingredients_data:
            FormulaIngredient.objects.create(
                formula=formula,
                raw_material=ingredient_data['raw_material'],
                quantity=ingredient_data['quantity'],
                unit=ingredient_data['unit'],
                notes=ingredient_data.get('notes', '')
            )
        
        return formula

    def update(self, instance, validated_data):
        # Don't allow updates to create new versions - use the create_new_version action instead
        ingredients_data = validated_data.pop('ingredients', [])
        
        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update ingredients - clear existing and create new ones
        instance.ingredients.all().delete()
        for ingredient_data in ingredients_data:
            FormulaIngredient.objects.create(
                formula=instance,
                raw_material=ingredient_data['raw_material'],
                quantity=ingredient_data['quantity'],
                unit=ingredient_data['unit'],
                notes=ingredient_data.get('notes', '')
            )
        
        return instance


class BatchRawMaterialSerializer(serializers.ModelSerializer):
    raw_material_details = StockSerializer(source='raw_material', read_only=True)
    unit_details = UnitSerializer(source='unit', read_only=True)
    
    class Meta:
        model = BatchRawMaterial
        fields = [
            'id', 'raw_material', 'raw_material_details', 
            'planned_quantity', 'actual_quantity', 
            'unit', 'unit_details', 'cost', 'notes'
        ]
        read_only_fields = ['id']


class QualityCheckSerializer(serializers.ModelSerializer):
    inspector_name = serializers.CharField(source='inspector.get_full_name', read_only=True)
    batch_details = serializers.SerializerMethodField()
    
    class Meta:
        model = QualityCheck
        fields = [
            'id', 'batch', 'check_date', 'inspector', 'inspector_name',
            'result', 'notes', 'created_at', 'batch_details'
        ]
        read_only_fields = ['id', 'created_at']

    def get_batch_details(self, obj):
        return {
            'id': obj.batch.id,
            'batch_number': obj.batch.batch_number,
            'formula': obj.batch.formula.name,
            'formula_version': obj.batch.formula.version,
            'status': obj.batch.status,
        }
    
    def create(self, validated_data):
        print("Validated Data:", validated_data)
        
        # Create quality check
        quality_check = QualityCheck.objects.create(**validated_data)
        
        return quality_check


class ProductionBatchSerializer(serializers.ModelSerializer):
    formula_details = ProductFormulaSerializer(source='formula', read_only=True)
    quality_checks = serializers.SerializerMethodField()
    creator_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    supervisor_name = serializers.CharField(source='supervisor.get_full_name', read_only=True)
    raw_material_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, 
        read_only=True, source='get_raw_material_cost'
    )
    total_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, 
        read_only=True, source='get_total_cost'
    )
    unit_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, 
        read_only=True, source='get_unit_cost'
    )
    
    class Meta:
        model = ProductionBatch
        fields = [
            'id', 'batch_number', 'formula', 'formula_details', 
            'location', 'scheduled_date', 'start_date', 'end_date',
            'status', 'planned_quantity', 'actual_quantity',
            'labor_cost', 'overhead_cost', 'raw_material_cost',
            'total_cost', 'unit_cost', 'notes', 'created_by',
            'creator_name', 'supervisor', 'supervisor_name',
            'created_at', 'updated_at', 'raw_materials', 'quality_checks'
        ]
        read_only_fields = [
            'id', 'batch_number', 'start_date', 'end_date',
            'created_by', 'created_at', 'updated_at'
        ]

    def get_quality_checks(self, obj):
        quality_checks = QualityCheck.objects.filter(batch=obj)
        return QualityCheckSerializer(quality_checks, many=True).data
    
    def create(self, validated_data):
        # Create batch
        batch = ProductionBatch.objects.create(**validated_data)
        
        return batch


class ManufacturingAnalyticsSerializer(serializers.ModelSerializer):
    total_cost = serializers.SerializerMethodField()
    average_cost_per_unit = serializers.SerializerMethodField()
    
    class Meta:
        model = ManufacturingAnalytics
        fields = [
            'id', 'date', 'total_batches', 'completed_batches', 
            'failed_batches', 'total_production_quantity',
            'total_raw_material_cost', 'total_labor_cost', 
            'total_overhead_cost', 'total_cost', 'average_cost_per_unit'
        ]
        read_only_fields = ['id']
    
    def get_total_cost(self, obj):
        return obj.total_raw_material_cost + obj.total_labor_cost + obj.total_overhead_cost
    
    def get_average_cost_per_unit(self, obj):
        if obj.total_production_quantity == 0:
            return 0
        total_cost = self.get_total_cost(obj)
        return total_cost / obj.total_production_quantity
