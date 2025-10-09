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
from crm.contacts.models import Contact
from ecommerce.stockinventory.models import StockInventory
from ecommerce.stockinventory.serializers import *
import json
from rest_framework.pagination import LimitOffsetPagination	
from django.db.models import Prefetch
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction

class ProductCRUDViewSet(viewsets.ModelViewSet):
    queryset = Products.objects.all().prefetch_related(
        'images',
        'category',
        'brand',
        'model'
    ).order_by('-created_at')
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = ()
    pagination_class = LimitOffsetPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ProductWriteSerializer
        return ProductsSerializer

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        images_data = request.FILES.getlist('images')

        with transaction.atomic():
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            product = serializer.save()

            # Handle image uploads
            for image_data in images_data:
                ProductImages.objects.create(product=product, image=image_data)

            headers = self.get_success_headers(serializer.data)
            return Response(
                ProductsSerializer(product, context=self.get_serializer_context()).data,
                status=status.HTTP_201_CREATED,
                headers=headers
            )

    def update(self, request, *args, **kwargs):
        category = request.data.get('category')
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        data = request.data.copy()
        images_data = request.FILES.getlist('images')

        with transaction.atomic():
            serializer = self.get_serializer(instance, data=data, partial=partial)
            serializer.is_valid(raise_exception=True)
            product = serializer.save()

            # Handle new image uploads
            if images_data:
                for image_data in images_data:
                    if image_data.name in [image.image.name for image in product.images.all()]:
                        continue
                    ProductImages.objects.create(product=product, image=image_data)

            return Response(
                ProductsSerializer(product, context=self.get_serializer_context()).data,
                status=status.HTTP_200_OK
            )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Delete associated images first
        instance.images.all().delete()
        
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

class CategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for all categories with their hierarchical structure
    """
    serializer_class = CategoriesSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly,]
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
        main_categories = Category.objects.filter(parent__isnull=True).prefetch_related(
            'children', 
            'children__children'
        )
        serializer = self.get_serializer(main_categories, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def children(self, request, pk=None):
        """Get direct children of a specific category"""
        category = self.get_object()
        children = category.children.all().prefetch_related('children')
        serializer = self.get_serializer(children, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def descendants(self, request, pk=None):
        """Get all descendants of a specific category"""
        category = self.get_object()
        descendants = []
        
        def get_descendants(cat):
            children = cat.children.all()
            for child in children:
                descendants.append(child)
                get_descendants(child)
        
        get_descendants(category)
        serializer = self.get_serializer(descendants, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def ancestors(self, request, pk=None):
        """Get all ancestors of a specific category"""
        category = self.get_object()
        ancestors = category.get_ancestors
        serializer = self.get_serializer(ancestors, many=True)
        return Response(serializer.data)

class MainCategoriesViewSet(viewsets.ModelViewSet):
    """
    ViewSet specifically for main categories (root categories with no parent)
    """
    serializer_class = MainCategoriesSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly,]
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        """Get only root categories (main categories)"""
        return Category.objects.filter(parent__isnull=True).prefetch_related(
            'children', 
            'children__children',
            'children__children__children'
        )

class VariationValuesViewSet(viewsets.ModelViewSet):
    queryset = Variations.objects.all()
    serializer_class = VariationSerializer
    permission_classes = [permissions.AllowAny,]
    pagination_class = LimitOffsetPagination  # Enable Limit and Offset Pagination

class VariationsViewSet(viewsets.ModelViewSet):
    queryset = Variations.objects.all()
    serializer_class = VariationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly,]
    pagination_class = LimitOffsetPagination  # Enable Limit and Offset Pagination