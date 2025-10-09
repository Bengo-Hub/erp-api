from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import *
from django.shortcuts import render
from datetime import date, datetime
from .models import *
from rest_framework.views import APIView
from rest_framework.response import Response
from ecommerce.pos.models import *
from django.http import Http404
from rest_framework.views import APIView
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework import permissions, authentication
from .serializers import *

# Create your views here.
class VendorViewSet(viewsets.ModelViewSet):
    queryset = Vendor.objects.all()
    serializer_class = VendoeSerializer
    permission_classes = [permissions.IsAuthenticated,]