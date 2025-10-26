from django.http import JsonResponse, Http404
from django.shortcuts import render
from datetime import date, datetime, timedelta
from .models import *
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets,status
from rest_framework.decorators import api_view, permission_classes
from rest_framework import permissions, authentication
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from django.db.models import Q,Count
from .serializers import *
from ecommerce.stockinventory.serializers import *
from ecommerce.stockinventory.models import Review, StockInventory
from ecommerce.product.models import *
from business.models import PickupStations
from .delivery import DeliveryPolicy, RegionalDeliveryPolicy, ProductDeliveryInfo
from rest_framework.pagination import PageNumberPagination
from django.db.models import Prefetch
from core.performance import monitor_performance, cache_result, optimize_list_queryset
from addresses.models import AddressBook, DeliveryRegion
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

class ProductViewSet(BaseModelViewSet):
    queryset = StockInventory.objects.all().prefetch_related(
        'product__images',
        'product__category',
        'product__brand',
        'product__model',
        'variation',
        'warranty',
        'discount',
        'reviews',
        'unit',
        'location',
        'supplier'
    ).all()
    serializer_class = StockSerializer
    #authentication_classes = []
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = PageNumberPagination  # Standardized: 100 records per page

    @monitor_performance('product_list_query')
    def get_queryset(self):
        queryset = super().get_queryset()
        # Get all query parameters
        params = self.request.query_params
        user = self.request.user
        
        # Basic pagination parameters
        limit = params.get('limit')
        offset = params.get('offset')
        
        # Search parameters - support both 'filter' (legacy) and 'search' (new)
        search_item = params.get('filter') or params.get('search')
        
        # Category filtering parameters
        category = params.get('category')  # Direct category ID
        categories = params.get('categories')  # Multiple categories as comma-separated IDs
        main_category = params.get('main_category')  # Main category ID
        
        # Brand filtering parameters
        brand = params.get('brand')  # Single brand
        brands = params.get('brands')  # Multiple brands as comma-separated IDs
        
        # Price range filtering
        min_price = params.get('min_price')
        max_price = params.get('max_price')
        
        # Rating filter
        min_rating = params.get('min_rating')
        
        # Stock availability filter
        in_stock = params.get('in_stock')
        
        # Special filters
        is_new = params.get('is_new')
        on_sale = params.get('on_sale')
        filter_type = params.get('filter')  # For special filter types like 'new', 'popular', 'sale'
        
        # Sorting parameters
        sort = params.get('sort')
        ordering = params.get('ordering')
        
        # Search filtering (both product name and description)
        if search_item:
            product_filter = Q(product__title__icontains=search_item) | \
                           Q(product__description__icontains=search_item) | \
                           Q(product__category__name__icontains=search_item) | \
                           Q(product__category__children__name__icontains=search_item) | \
                           Q(product__sku__icontains=search_item) | \
                           Q(product__serial__icontains=search_item)
            
            queryset = queryset.filter(product_filter)
        
        # Direct category ID filtering
        if category:
            queryset = queryset.filter(
                Q(product__category_id=category) |
                Q(product__category__children__id=category) |
                Q(product__category__children__children__id=category)
            ).distinct()
        
        # Multiple categories filtering
        if categories:
            category_ids = [int(c.strip()) for c in categories.split(',') if c.strip().isdigit()]
            if category_ids:
                category_filter = Q()
                for cat_id in category_ids:
                    category_filter |= Q(product__category_id=cat_id) | \
                                       Q(product__category__children__id=cat_id) | \
                                       Q(product__category__children__children__id=cat_id)
                queryset = queryset.filter(category_filter).distinct()
        
        # Main category filtering
        if main_category:
            queryset = queryset.filter(product__category_id=main_category).distinct()
        
        # Single brand filtering
        if brand:
            queryset = queryset.filter(product__brand_id=brand)
        
        # Multiple brands filtering
        if brands:
            brand_ids = [int(b.strip()) for b in brands.split(',') if b.strip().isdigit()]
            if brand_ids:
                queryset = queryset.filter(product__brand_id__in=brand_ids)
        
        # Price range filtering
        if min_price and max_price:
            queryset = queryset.filter(selling_price__gte=min_price, selling_price__lte=max_price)
        elif min_price:
            queryset = queryset.filter(selling_price__gte=min_price)
        elif max_price:
            queryset = queryset.filter(selling_price__lte=max_price)
        
        # Rating filter
        if min_rating:
            try:
                min_rating_value = float(min_rating)
                # Filter products with average rating >= min_rating
                # This assumes you have a way to calculate average_rating
                queryset = queryset.filter(reviews__rating__gte=min_rating_value).distinct()
            except (ValueError, TypeError):
                pass
        
        # Stock availability filter
        if in_stock and in_stock.lower() in ['true', '1', 'yes']:
            queryset = queryset.filter(stock_level__gt=0)
        
        # Special filter types
        if filter_type:
            if filter_type == 'new':
                # Products created in the last 30 days
                from django.utils import timezone
                import datetime
                thirty_days_ago = timezone.now() - datetime.timedelta(days=30)
                queryset = queryset.filter(product__created_at__gte=thirty_days_ago)
            elif filter_type == 'popular':
                # Products with highest view counts or sales
                queryset = queryset.order_by('-view_count')
            elif filter_type in ['sale', 'flash']:
                # Products that have a discount active
                queryset = queryset.filter(discount__isnull=False, discount__is_active=True)
        
        # Sale filter (separate from filter_type)
        if on_sale and on_sale.lower() in ['true', '1', 'yes']:
            queryset = queryset.filter(discount__isnull=False, discount__is_active=True)
        
        # Products created in last 30 days
        if is_new and is_new.lower() in ['true', '1', 'yes']:
            from django.utils import timezone
            import datetime
            thirty_days_ago = timezone.now() - datetime.timedelta(days=30)
            queryset = queryset.filter(product__created_at__gte=thirty_days_ago)
        
        # Sorting
        if sort:
            if sort == '-created_at':
                queryset = queryset.order_by('-product__created_at')
            elif sort == '-total_sales':
                # This would need a way to track sales per product
                queryset = queryset.order_by('-view_count')  # Fallback to view count as proxy for popularity
            elif sort == 'price':
                queryset = queryset.order_by('selling_price')
            elif sort == '-price':
                queryset = queryset.order_by('-selling_price')
            elif sort == '-average_rating':
                # This would need a way to calculate average rating
                # For now, using a simple group by and annotate approach
                from django.db.models import Avg
                queryset = queryset.annotate(avg_rating=Avg('reviews__rating')).order_by('-avg_rating')
        elif ordering:  # Legacy ordering parameter
            if ordering in ['selling_price', '-selling_price', 'product__created_at', '-product__created_at']:
                queryset = queryset.order_by(ordering)
            else:
                # Default ordering
                queryset = queryset.order_by('-product__created_at')
        
        # Apply pagination if specified
        if limit is not None and offset is not None:
            paginator = LimitOffsetPagination()
            paginated_queryset = paginator.paginate_queryset(queryset, self.request, view=self)
            return paginated_queryset

        return queryset

    def retrieve(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            data = serializer.data
            
            # Check if user is authenticated and get their favorites
            if request.user.is_authenticated:
                favorite = Favourites.objects.filter(user=request.user, stock=instance).exists()
                data['is_favorite'] = favorite
            else:
                data['is_favorite'] = False
                
            # Get related products
            related_products = self.get_related_products(instance.product)
            related_serializer = StockSerializer(related_products, many=True, context={'request': request})
            data['related_products'] = related_serializer.data
            
            # Add delivery information
            self.add_delivery_info(data, instance.product, request)
            
            # Increment view count
            instance.product.view_count = instance.product.view_count + 1
            instance.product.save()
            
            return APIResponse.success(data=data, message='Product retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error retrieving product: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving product', error_id=str(e), correlation_id=get_correlation_id(request))
        
    @action(detail=False, methods=['get'])
    def delivery_options(self, request):
        """
        Return standard delivery options available in the system
        """
        try:
            correlation_id = get_correlation_id(request)
            # Default delivery options
            delivery_options = [
                {
                    'id': 1,
                    'name': 'Standard Delivery',
                    'fee': 200,
                    'description': 'Delivery within 2-5 business days',
                    'is_default': True
                },
                {
                    'id': 2,
                    'name': 'Express Delivery',
                    'fee': 500,
                    'description': 'Next day delivery for orders placed before 2pm',
                    'is_default': False
                }
            ]
            
            # Try to get any custom delivery options from the database if available
            try:
                # This is a flexible approach to support custom delivery options
                # from different modules if they're implemented in the future
                from ecommerce.order.models import DeliveryOption
                db_options = DeliveryOption.objects.filter(is_active=True)
                if db_options.exists():
                    delivery_options = []
                    for option in db_options:
                        delivery_options.append({
                            'id': option.id,
                            'name': option.name,
                            'fee': option.fee,
                            'description': option.description,
                            'is_default': option.is_default
                        })
            except ImportError:
                # DeliveryOption model might not exist, use defaults
                pass
            except Exception as e:
                # Log error but continue with default options
                print(f"Error fetching delivery options: {str(e)}")
            
            return APIResponse.success(data=delivery_options, message='Delivery options retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching delivery options: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving delivery options', error_id=str(e), correlation_id=get_correlation_id(request))

    def get_related_products(self, product):
        """Get products related to the current product based on category and brand"""
        # Find products in the same category or by the same brand
        related = StockInventory.objects.filter(
            Q(product__category=product.category) | Q(product__brand=product.brand)
        ).exclude(product=product).distinct()[:5]  # Limit to 5 related products
        
        return related
        
    def add_delivery_info(self, data, product, request):
        """Add delivery information to product data"""
        # Default delivery information
        delivery_info = {
            'estimated_delivery': {
                'min_days': 2,
                'max_days': 5,
                'min_date': (datetime.now() + timedelta(days=2)).strftime('%d %b %Y'),
                'max_date': (datetime.now() + timedelta(days=5)).strftime('%d %b %Y'),
            },
            'delivery_options': [
                {
                    'name': 'Standard Delivery',
                    'fee': 200,
                    'description': 'Delivery within 2-5 business days',
                    'is_default': True
                },
                {
                    'name': 'Express Delivery',
                    'fee': 500,
                    'description': 'Next day delivery for orders placed before 2pm',
                    'is_default': False
                }
            ],
            'pickup_available': True,
            'pickup_stations': []
        }
        
        # Try to get the specific product delivery info if it exists
        try:
            product_delivery = ProductDeliveryInfo.objects.filter(product=product).first()
            if product_delivery:
                # Get user's region if available
                region = None
                if request.user.is_authenticated:
                    # Try to get user's default address region
                    try:
                        default_address = AddressBook.objects.filter(user=request.user, default_address=True).first()
                        if default_address and default_address.address:
                            region = default_address.address.region
                    except:
                        pass
                
                # Get estimated delivery times
                min_days, max_days = product_delivery.get_estimated_delivery_days(region)
                delivery_info['estimated_delivery']['min_days'] = min_days
                delivery_info['estimated_delivery']['max_days'] = max_days
                delivery_info['estimated_delivery']['min_date'] = (datetime.now() + timedelta(days=min_days)).strftime('%d %b %Y')
                delivery_info['estimated_delivery']['max_date'] = (datetime.now() + timedelta(days=max_days)).strftime('%d %b %Y')
                
                # Special delivery flags
                if product_delivery.is_jumia_express:
                    delivery_info['jumia_express'] = True
                    
                if product_delivery.is_jumia_prime:
                    delivery_info['jumia_prime'] = True
        except Exception as e:
            # Log error but continue with default info
            print(f"Error adding delivery info: {str(e)}")
            
        # Add pickup stations
        try:
            pickup_stations = PickupStations.objects.all()[:5]
            pickup_stations_data = []
            for station in pickup_stations:
                pickup_stations_data.append({
                    'id': station.id,
                    'name': station.pickup_location,
                    'region': station.region.region if station.region else 'Unknown',
                    'fee': station.shipping_charge,
                    'description': station.description or '',
                    'open_hours': station.open_hours
                })
            delivery_info['pickup_stations'] = pickup_stations_data
        except Exception as e:
            # Log error but continue
            print(f"Error adding pickup stations: {str(e)}")
            
        data['delivery_info'] = delivery_info

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'],url_path="featured",name="featured")
    def featured(self, request):
        """
        Return featured products (products marked as featured or with high ratings)
        """
        try:
            correlation_id = get_correlation_id(request)
            queryset = self.get_queryset().filter(
                Q(is_top_pick=True) | Q(is_new_arrival=True) |
                Q(reviews__rating__gte=4)
            ).distinct()[:8]
            
            serializer = self.get_serializer(queryset, many=True)
            return APIResponse.success(data=serializer.data, message='Featured products retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching featured products: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving featured products', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=False, methods=['get',],name="trending",url_path="trending")
    def trending(self, request):
        """
        Return trending products (most viewed or recently popular products)
        """
        try:
            correlation_id = get_correlation_id(request)
            # You could implement more complex logic based on views or purchases
            queryset = self.get_queryset().order_by('-product__view_count')[:8]
            serializer = self.get_serializer(queryset, many=True)
            return APIResponse.success(data=serializer.data, message='Trending products retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching trending products: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving trending products', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=False, methods=['get'],name="recommended",url_path="recommended")
    def recommended(self, request):
        """
        Return recommended products for the current user or generally popular products
        """
        try:
            correlation_id = get_correlation_id(request)
            user = request.user
            
            if user.is_authenticated:
                # Get user's purchase history categories
                # This is a simplified version - you'd typically use a more sophisticated algorithm
                favourites = Favourites.objects.filter(user=user).values_list('stock_id', flat=True)
                
                if favourites.exists():
                    # Get products from similar categories as user's favorites
                    favorite_products = StockInventory.objects.filter(id__in=favourites)
                    fav_categories = set()
                    for product in favorite_products:
                        fav_categories.add(product.category.id)
                        
                    queryset = self.get_queryset().filter(
                        product__category__id__in=fav_categories
                    ).exclude(product__id__in=favourites)[:8]
                    
                    serializer = self.get_serializer(queryset, many=True)
                    return APIResponse.success(data=serializer.data, message='Recommended products retrieved successfully', correlation_id=correlation_id)
            
            # Default: return highly rated products
            queryset = self.get_queryset().filter(
                reviews__rating__gte=4
            ).distinct().order_by('?')[:8]  # Random selection
            
            serializer = self.get_serializer(queryset, many=True)
            return APIResponse.success(data=serializer.data, message='Recommended products retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching recommended products: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving recommended products', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=False, methods=['get'],name="flash_sale",url_path="flash-sale")
    def flash_sale(self, request):
        """
        Return products that are currently part of a flash sale
        """
        try:
            correlation_id = get_correlation_id(request)
            today = date.today()
            queryset = self.get_queryset().filter(
                Q(discount__percentage__gt=0) |
                Q(discount__discount_amount__gt=0),
                discount__isnull=False,
                discount__start_date__lte=today,
                discount__end_date__gte=today
            ).order_by('-discount__percentage')[:8]
            
            serializer = self.get_serializer(queryset, many=True)
            return APIResponse.success(data=serializer.data, message='Flash sale products retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching flash sale products: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving flash sale products', error_id=str(e), correlation_id=get_correlation_id(request))

class ProductDetail(APIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly,]
    def get_object(self, pk):
        try:
            return Products.objects.get(pk=pk)
        except Products.DoesNotExist:
            raise Http404

    def get(self, request, pk):
        try:
            correlation_id = get_correlation_id(request)
            cart = self.get_object(pk)
            serializer = ProductsSerializer(cart)
            return APIResponse.success(data=serializer.data, message='Product detail retrieved successfully', correlation_id=correlation_id)
        except Http404:
            return APIResponse.not_found(message='Product not found', correlation_id=get_correlation_id(request))
        except Exception as e:
            logger.error(f'Error fetching product detail: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving product detail', error_id=str(e), correlation_id=get_correlation_id(request))

class ReviewsViewSet(BaseModelViewSet):
    queryset = Review.objects.all().select_related('stock__product')
    serializer_class = ReviewsSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        # Apply filters based on query parameters
        sku = self.request.query_params.get('sku', None)
        if sku is not None:
            queryset = queryset.filter(Q(stock__product__sku=sku)|Q(stock__variation__sku=sku))
        return queryset

    def create(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Review validation failed', errors=serializer.errors, correlation_id=correlation_id)
            instance = serializer.save()
            AuditTrail.log(operation=AuditTrail.CREATE, module='ecommerce', entity_type='Review', entity_id=instance.id, user=request.user, reason=f'Created product review', request=request)
            return APIResponse.created(data=self.get_serializer(instance).data, message='Review created successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error creating review: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error creating review', error_id=str(e), correlation_id=get_correlation_id(request))

class FavouriteViewSet(BaseModelViewSet):
    serializer_class = FavouritesSerializer
    queryset = Favourites.objects.prefetch_related(
        'stock__product',
        'stock__product__images',
        'stock__product__category',
        'stock__product__brand',
        'stock__variation',
        'stock__discount',
        'stock__unit',
        'stock__reviews',
        'stock__location',
    ).all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
     
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Favourites.objects.none()
        queryset = super().get_queryset()
        return queryset.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        """Add product to favorites"""
        try:
            correlation_id = get_correlation_id(request)
            product_id = request.data.get('product_id')
            if not product_id:
                return APIResponse.bad_request(message='Product ID is required', error_id='missing_product_id', correlation_id=correlation_id)
                
            try:
                product = StockInventory.objects.get(id=product_id)
            except StockInventory.DoesNotExist:
                return APIResponse.not_found(message='Product not found', correlation_id=correlation_id)
                
            favorite, created = Favourites.objects.get_or_create(
                user=request.user,
                stock=product
            )
            
            if not created:
                return APIResponse.success(data=self.get_serializer(favorite).data, message='Product already in favorites', correlation_id=correlation_id)
            
            AuditTrail.log(operation=AuditTrail.CREATE, module='ecommerce', entity_type='Favourite', entity_id=favorite.id, user=request.user, reason='Product added to favorites', request=request)
            return APIResponse.created(data=self.get_serializer(favorite).data, message='Product added to favorites', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error adding to favorites: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error adding to favorites', error_id=str(e), correlation_id=get_correlation_id(request))
    
    def destroy(self, request, pk=None):
        """Remove product from favorites"""
        try:
            correlation_id = get_correlation_id(request)
            favorite = self.get_object()
            AuditTrail.log(operation=AuditTrail.DELETE, module='ecommerce', entity_type='Favourite', entity_id=favorite.id, user=request.user, reason='Product removed from favorites', request=request)
            favorite.delete()
            return APIResponse.success(message='Product removed from favorites', correlation_id=correlation_id)
        except Favourites.DoesNotExist:
            return APIResponse.not_found(message='Favourite not found', correlation_id=get_correlation_id(request))
        except Exception as e:
            logger.error(f'Error removing from favorites: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error removing from favorites', error_id=str(e), correlation_id=get_correlation_id(request))

#Brands
class BrandsViewSet(BaseModelViewSet):
    queryset = ProductBrands.objects.all()
    serializer_class = BrandsSerializer
    permission_classes = [permissions.AllowAny]

#Models

class ModelsViewSet(BaseModelViewSet):
    queryset = ProductModels.objects.all()
    serializer_class = ModelsSerializer
    permission_classes = [permissions.AllowAny]

class Home(APIView):
    permission_classes = ([permissions.IsAuthenticatedOrReadOnly,])

    def get(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            now = datetime.now()
            current_year = now.year
            current_month = now.month
            current_day = now.day
            categories = len(Category.objects.all())
            products = len(Products.objects.all())
            transaction = len(Sales.objects.filter(
                date_added__year=current_year,
                date_added__month=current_month,
                date_added__day=current_day
            ))
            today_sales = Sales.objects.filter(
                date_added__year=current_year,
                date_added__month=current_month,
                date_added__day=current_day
            ).all()
            total_sales = sum(today_sales.values_list('grand_total', flat=True))
            context = {
                'categories': categories,
                'products': products,
                'transaction': transaction,
                'total_sales': total_sales,
            }
            return APIResponse.success(data=context, message='Home statistics retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching home stats: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving home statistics', error_id=str(e), correlation_id=get_correlation_id(request))