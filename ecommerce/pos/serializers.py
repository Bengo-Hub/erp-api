from rest_framework import routers, serializers, viewsets
from django.db import models
from .models import *
from django.contrib.auth import get_user_model
from ecommerce.stockinventory.serializers import StockSerializer
from crm.contacts.serializers import ContactSerializer
from hrm.employees.models import Employee
from hrm.payroll.models import Advances
from hrm.payroll.serializers import EmployeeAdvancesSerializer
from .services import StaffAdvanceService

User = get_user_model()
# Serializers define the API representation.
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model=User
        fields=['id','username','first_name','last_name']

class CustomerSerializer(serializers.ModelSerializer):
    user=UserSerializer()
    class Meta:
        model=Contact
        fields=['id','user']

class SalesSerializer(serializers.ModelSerializer):
    branch_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Sales
        fields = '__all__'  # Keep existing fields but add branch via method

    def get_branch_id(self, obj):
        try:
            return obj.register.branch.id if obj.register and obj.register.branch else None
        except Exception:
            return None

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MpesaTransaction
        fields = '__all__'

class SaleStockItemSerializer(serializers.ModelSerializer):
    class Meta:
        model=StockInventory
        fields=['product','variation','product_type']

class SalesItemsSerializer(serializers.ModelSerializer):
    sale_id = SalesSerializer()
    stocks=SaleStockItemSerializer()

    class Meta:
        model = salesItems
        fields = '__all__'
        # Prevent deep automatic nesting which can expand business objects with timezone
        depth = 0

class CustomerRewardSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerReward
        fields = ['id', 'customer', 'amount', 'description', 'date_created']

class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Register
        fields = '__all__'

class SaleItemDetailSerializer(serializers.ModelSerializer):
    stock_item = StockSerializer()
    
    class Meta:
        model = salesItems
        fields = ['id', 'stock_item', 'qty', 'unit_price', 'sub_total', 'tax_amount', 'discount_amount']
        depth = 0

class SalesDetailSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer()
    attendant = UserSerializer()
    sales_items = SaleItemDetailSerializer(many=True, source='salesitems')
    
    class Meta:
        model = Sales
        fields = ['id', 'sale_id', 'customer', 'attendant', 'date_added', 'grand_total', 
                 'amount_paid', 'balance_due', 'payment_status', 'status', 'paymethod', 
                 'sell_note', 'staff_note', 'sales_items', 'sale_tax', 'sale_discount', 'sub_total']
        depth = 0

    branch_id = serializers.SerializerMethodField(read_only=True)

    def get_branch_id(self, obj):
        try:
            return obj.register.branch.id if obj.register and obj.register.branch else None
        except Exception:
            return None

class SuspendedSaleSerializer(serializers.ModelSerializer):
    customer = ContactSerializer(read_only=True)
    customer_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    attendant_name = serializers.SerializerMethodField()

    class Meta:
        model = SuspendedSale
        fields = '__all__'
        read_only_fields = ('reference_number',)

    def get_attendant_name(self, obj):
        return f"{obj.attendant.first_name} {obj.attendant.last_name}" if obj.attendant else "System"

    def create(self, validated_data):
        # Generate a unique reference number
        from .utils import generate_suspended_sale_reference
        validated_data['reference_number'] = generate_suspended_sale_reference()
        
        # Handle customer_id
        customer_id = validated_data.pop('customer_id', None)
        if customer_id:
            validated_data['customer'] = Contact.objects.get(id=customer_id)
        
        return super().create(validated_data)


# Staff Advance Serializers
class POSAdvanceSaleRecordSerializer(serializers.ModelSerializer):
    advance = EmployeeAdvancesSerializer(read_only=True)
    
    class Meta:
        model = POSAdvanceSaleRecord
        fields = '__all__'
        read_only_fields = ['reference_id', 'created_by']

class StaffAdvanceBalanceSerializer(serializers.ModelSerializer):
    available_advance = serializers.SerializerMethodField()
    
    class Meta:
        model = Employee
        fields = ['id', 'available_advance']
    
    def get_available_advance(self, obj):
        # Calculate based on employee's salary and existing advances
        max_advance = getattr(obj, 'max_advance', 5000)  # Default max advance
        
        # Get the sum of all active advances for this employee
        active_advances = Advances.objects.filter(
            employee=obj,
            is_active=True
        ).aggregate(models.Sum('amount_issued'))['amount_issued__sum'] or 0
        
        # Get the sum of all amounts repaid
        repaid_amounts = Advances.objects.filter(
            employee=obj,
            is_active=True
        ).aggregate(models.Sum('amount_repaid'))['amount_repaid__sum'] or 0
        
        # Calculate current advances
        current_advances = active_advances - repaid_amounts
        
        # Calculate available balance
        available_advance = max_advance - current_advances
        return max(0, available_advance)

class CreateStaffAdvanceSaleSerializer(serializers.Serializer):
    staff_id = serializers.IntegerField()
    cart_items = serializers.ListField(child=serializers.JSONField())
    advance_type = serializers.ChoiceField(choices=[('salary_advance', 'Salary Advance'), ('loan_repayment', 'Loan Repayment')])
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    installments = serializers.IntegerField(min_value=1, default=1)
    note = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, attrs):
        try:
            staff = Employee.objects.get(id=attrs['staff_id'])
        except Employee.DoesNotExist:
            raise serializers.ValidationError({"staff_id": "Employee not found"})
        
        # Validate cart items
        if not attrs['cart_items']:
            raise serializers.ValidationError({"cart_items": "Cart cannot be empty"})
        
        # For salary advances, check if amount exceeds available advance limit
        if attrs['advance_type'] == 'salary_advance':
            max_advance = getattr(staff, 'max_advance', 5000)  # Default max advance
            
            # Get the sum of all active advances for this employee
            active_advances = Advances.objects.filter(
                employee=staff,
                is_active=True
            ).aggregate(models.Sum('amount_issued'))['amount_issued__sum'] or 0
            
            # Get the sum of all amounts repaid
            repaid_amounts = Advances.objects.filter(
                employee=staff,
                is_active=True
            ).aggregate(models.Sum('amount_repaid'))['amount_repaid__sum'] or 0
            
            # Calculate current advances
            current_advances = active_advances - repaid_amounts
            
            # Calculate available balance
            available_advance = max_advance - current_advances
            
            if attrs['total_amount'] > available_advance:
                raise serializers.ValidationError({
                    "total_amount": f"Amount exceeds available advance limit. Available: {available_advance}"
                })
        
        return attrs
    
    def create(self, validated_data):
        # Use the service function to create the staff advance sale
        pos_record = StaffAdvanceService.create_staff_advance_sale(
            staff_id=validated_data['staff_id'],
            cart_items=validated_data['cart_items'],
            amount=validated_data['total_amount'],
            advance_type=validated_data['advance_type'],
            installments=validated_data.get('installments', 1),
            note=validated_data.get('note', ''),
            user=self.context['request'].user
        )
        
        return pos_record