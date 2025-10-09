
from rest_framework import serializers
from .models import *
from rest_framework import status
from rest_framework.response import Response
from django.contrib.auth import get_user_model


class VendoeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = '__all__'
        depth = 3
