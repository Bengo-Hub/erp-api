from rest_framework import serializers
from .models import *
from django.contrib.auth import get_user_model


User = get_user_model()
# Serializers define the API representation.
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model=User
        fields=['id','username','first_name','last_name']

class SupplierSerializer(serializers.ModelSerializer):
    user=UserSerializer()
    class Meta:
        model=Contact
        fields=['id','user']

class PurchasesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Purchase
        fields = '__all__'

class PurchaseStockItemSerializer(serializers.ModelSerializer):
    class Meta:
        model=StockInventory
        fields=['product','variation','product_type']

class PurchaseItemsSerializer(serializers.ModelSerializer):
    purchase = PurchasesSerializer()
    stock=PurchaseStockItemSerializer()

    class Meta:
        model = PurchaseItems
        fields = '__all__'
        depth = 2
