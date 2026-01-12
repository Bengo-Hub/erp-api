
from rest_framework import serializers
from .models import Contact,CustomerGroup,ContactAccount
from business.models import Bussiness
from rest_framework import status
from rest_framework.response import Response

from django.contrib.auth import get_user_model
User=get_user_model()

class ContactUserSerializer(serializers.ModelSerializer):
    class Meta:
        model=User
        fields=['id','username','first_name','last_name','email','phone']

class ContactCustomerGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        fields = ('id', 'group_name')

class ContactAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactAccount
        fields = ('account_balance','advance_balance')

class ContactLocationSerializer(serializers.Serializer):
    """Minimal location/branch information"""
    id = serializers.IntegerField(read_only=True)
    city = serializers.CharField(read_only=True, allow_null=True)
    country = serializers.CharField(read_only=True, allow_null=True)
    county = serializers.CharField(read_only=True, allow_null=True)

class ContactSerializer(serializers.ModelSerializer):
    user=ContactUserSerializer()
    customer_group=ContactCustomerGroupSerializer(required=False, allow_null=True)
    accounts=ContactAccountSerializer(many=True, read_only=True)
    # Use DateTimeField to match the model's DateTimeField, not DateField
    added_on = serializers.SerializerMethodField(read_only=True)
    
    def get_added_on(self, obj):
        """Return added_on as ISO datetime string."""
        if obj.added_on:
            return obj.added_on.isoformat()
        return None
    
    class Meta:
        model = Contact
        fields = ['id', 'contact_id', 'contact_type', 'user', 'designation', 'customer_group', 'account_type',
                  'tax_number', 'business_name', 'business_address', 'director_first_name', 'director_last_name', 
                  'alternative_contact', 'phone', 'landline', 'credit_limit', 'added_on', 'accounts']

class CustomerGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        fields = '__all__'

