
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

class BussinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bussiness
        fields =('name',)

class ContactCustomerGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        fields = ('group_name',)

class ContactAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactAccount
        fields = ('account_balance','advance_balance')
        
class ContactSerializer(serializers.ModelSerializer):
    user=ContactUserSerializer()
    created_by=ContactUserSerializer(required=False,read_only=True)
    customer_group=ContactCustomerGroupSerializer()
    accounts=ContactAccountSerializer(many=True, read_only=True)
    class Meta:
        model = Contact
        fields = ['id', 'contact_id', 'contact_type', 'user', 'location', 'designation', 'customer_group', 'account_type',
                  'tax_number', 'business_name', 'business_address', 'alternative_contact', 'phone', 'credit_limit', 'added_on','accounts', 'created_by']

class CustomerGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        fields = '__all__'

