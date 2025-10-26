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
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework import permissions, authentication
from .serializers import *
from crm.contacts.models import Contact
from ecommerce.stockinventory.models import StockInventory
from ecommerce.stockinventory.serializers import *
import json
from rest_framework.pagination import LimitOffsetPagination	
from django.db.models import Prefetch
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)

class ProductCRUDViewSet(BaseModelViewSet):
    queryset = Products.objects.all().prefetch_related(
        'images',
        'category',
        'brand',
        'model'
    ).order_by('-created_at')
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = LimitOffsetPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ProductWriteSerializer
        return ProductsSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            data = request.data.copy()
            images_data = request.FILES.getlist('images')

            serializer = self.get_serializer(data=data)
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Product validation failed', errors=serializer.errors, correlation_id=correlation_id)
            
            product = serializer.save()

            # Handle image uploads
            for image_data in images_data:
                ProductImages.objects.create(product=product, image=image_data)

            AuditTrail.log(operation=AuditTrail.CREATE, module='ecommerce', entity_type='Product', entity_id=product.id, user=request.user, reason='Created product', request=request)
            
            return APIResponse.created(
                data=ProductsSerializer(product, context=self.get_serializer_context()).data,
                message='Product created successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error creating product: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error creating product', error_id=str(e), correlation_id=get_correlation_id(request))

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            partial = kwargs.pop('partial', False)
            instance = self.get_object()
            data = request.data.copy()
            images_data = request.FILES.getlist('images')

            serializer = self.get_serializer(instance, data=data, partial=partial)
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Product validation failed', errors=serializer.errors, correlation_id=correlation_id)
            
            product = serializer.save()

            # Handle new image uploads
            if images_data:
                for image_data in images_data:
                    if image_data.name in [image.image.name for image in product.images.all()]:
                        continue
                    ProductImages.objects.create(product=product, image=image_data)

            AuditTrail.log(operation=AuditTrail.UPDATE, module='ecommerce', entity_type='Product', entity_id=product.id, user=request.user, reason='Updated product', request=request)
            
            return APIResponse.success(
                data=ProductsSerializer(product, context=self.get_serializer_context()).data,
                message='Product updated successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error updating product: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error updating product', error_id=str(e), correlation_id=get_correlation_id(request))

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            instance = self.get_object()
            
            # Delete associated images first
            instance.images.all().delete()
            
            instance.delete()
            AuditTrail.log(operation=AuditTrail.DELETE, module='ecommerce', entity_type='Product', entity_id=instance.id, user=request.user, reason='Deleted product', request=request)
            
            return APIResponse.success(message='Product deleted successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error deleting product: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error deleting product', error_id=str(e), correlation_id=get_correlation_id(request))

class CategoryViewSet(BaseModelViewSet):
    """
    ViewSet for all categories with their hierarchical structure
    """
    serializer_class = CategoriesSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """Get categories with their children prefetched"""
        return Category.objects.prefetch_related(
            'children', 
            'children__children',
            'children__children__children'
        ).all()

    @action(detail=False, methods=['get'])
    def main_categories(self, request):
        """Get only root categories (main categories with no parent)"""
        try:
            correlation_id = get_correlation_id(request)
            main_categories = Category.objects.filter(parent__isnull=True).prefetch_related(
                'children', 
                'children__children'
            )
            serializer = self.get_serializer(main_categories, many=True)
            return APIResponse.success(data=serializer.data, message='Main categories retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching main categories: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving main categories', error_id=str(e), correlation_id=get_correlation_id(request))

    @action(detail=True, methods=['get'])
    def children(self, request, pk=None):
        """Get direct children of a specific category"""
        try:
            correlation_id = get_correlation_id(request)
            category = self.get_object()
            children = category.children.all().prefetch_related('children')
            serializer = self.get_serializer(children, many=True)
            return APIResponse.success(data=serializer.data, message='Category children retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching category children: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving category children', error_id=str(e), correlation_id=get_correlation_id(request))

    @action(detail=True, methods=['get'])
    def descendants(self, request, pk=None):
        """Get all descendants of a specific category"""
        try:
            correlation_id = get_correlation_id(request)
            category = self.get_object()
            descendants = []
            
            def get_descendants(cat):
                children = cat.children.all()
                for child in children:
                    descendants.append(child)
                    get_descendants(child)
            
            get_descendants(category)
            serializer = self.get_serializer(descendants, many=True)
            return APIResponse.success(data=serializer.data, message='Category descendants retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching category descendants: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving category descendants', error_id=str(e), correlation_id=get_correlation_id(request))

    @action(detail=True, methods=['get'])
    def ancestors(self, request, pk=None):
        """Get all ancestors of a specific category"""
        try:
            correlation_id = get_correlation_id(request)
            category = self.get_object()
            ancestors = category.get_ancestors
            serializer = self.get_serializer(ancestors, many=True)
            return APIResponse.success(data=serializer.data, message='Category ancestors retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching category ancestors: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving category ancestors', error_id=str(e), correlation_id=get_correlation_id(request))

class MainCategoriesViewSet(BaseModelViewSet):
    """
    ViewSet specifically for main categories (root categories with no parent)
    """
    serializer_class = MainCategoriesSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """Get only root categories (main categories)"""
        return Category.objects.filter(parent__isnull=True).prefetch_related(
            'children', 
            'children__children',
            'children__children__children'
        )

class VariationValuesViewSet(BaseModelViewSet):
    queryset = Variations.objects.all()
    serializer_class = VariationSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = LimitOffsetPagination

class VariationsViewSet(BaseModelViewSet):
    queryset = Variations.objects.all()
    serializer_class = VariationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = LimitOffsetPagination