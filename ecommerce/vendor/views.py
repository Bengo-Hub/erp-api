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
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)

# Create your views here.
class VendorViewSet(BaseModelViewSet):
    queryset = Vendor.objects.all()
    serializer_class = VendoeSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def create(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Vendor validation failed', errors=serializer.errors, correlation_id=correlation_id)
            instance = serializer.save()
            AuditTrail.log(operation=AuditTrail.CREATE, module='ecommerce', entity_type='Vendor', entity_id=instance.id, user=request.user, reason='Created vendor', request=request)
            return APIResponse.created(data=self.get_serializer(instance).data, message='Vendor created successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error creating vendor: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error creating vendor', error_id=str(e), correlation_id=get_correlation_id(request))