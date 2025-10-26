import logging
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import viewsets, permissions, authentication, status, filters
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import render
from django.http import Http404
from django.db.models import Q, Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import TruncDate
from datetime import date, datetime, timedelta
import django.utils.timezone as django_timezone
from .models import Products, StockInventory, StockTransaction, StockTransfer, StockAdjustment, Unit
from .serializers import *
from ecommerce.vendor.models import Vendor
from business.models import BusinessLocation, Branch
from core.utils import get_branch_id_from_request
from core.performance import monitor_performance, cache_result, optimize_list_queryset
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from django.db import transaction

# Create your views here.
logger = logging.getLogger(__name__)


class InventoryViewSet(BaseModelViewSet):
    queryset = StockInventory.objects.all().order_by('product__id','-created_at').distinct()
    serializer_class = StockSerializer
    authentication_classes = []
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = PageNumberPagination  # Standardized: 100 records per page

    @monitor_performance('inventory_list_query')
    def get_queryset(self):
        queryset = super().get_queryset()
        limit = self.request.query_params.get('limit', 8)
        offset = self.request.query_params.get('offset', 0)
        prod_id = self.request.query_params.get('prod_id', None)
        filter = self.request.query_params.get('filter', None)
        search_item = self.request.query_params.get('search', None)
        search=search_item if search_item else filter

        user = self.request.user

        #define filters
        filters = Q( 
            Q(product__category__name__icontains=search) |
            Q(product__category__children__name__icontains=search) |
            Q(product__sku__icontains=search) |
            Q(id__icontains=search) |
            Q(product__serial__icontains=search) |
            Q(variations__serial__icontains=search) |
            Q(product__title__icontains=search) |
            Q(product__description__icontains=search) |
            Q(product__brand__title__icontains=search) |
            Q(variations__sku__icontains=search) |
            Q(variations__title__icontains=search) 
            )
        if search_item and not user.is_authenticated:
            queryset = queryset.filter(filters).distinct()

        if user.is_authenticated:
            if search:
                if user !=None:
                    queryset = queryset.filter(filters & Q(location__owner__user=user)).distinct()
                else:
                    queryset = queryset.filter(filters).distinct()

            if prod_id !=None:
                queryset = queryset.filter(product__id=prod_id).distinct()

        # Apply pagination
        if limit and offset:
            queryset = queryset[int(offset):int(offset) + int(limit)]
        elif limit:
            queryset = queryset[:int(limit)]
        return queryset
    
    @action(detail=False, methods=['get'], url_path='valuation', url_name='valuation')
    def valuation(self, request):
        try:
            correlation_id = get_correlation_id(request)
            queryset = self.queryset
            
            # Filter by location if provided
            branch_id = request.query_params.get('branch_id') or get_branch_id_from_request(request)
            if branch_id:
                queryset = queryset.filter(branch_id=branch_id)
            
            # Calculate total valuation
            total_valuation = queryset.aggregate(
                total_value=Sum(F('stock_level') * F('buying_price'))
            )['total_value'] or 0
            
            # Get valuation by category
            valuation_by_category = queryset.values(
                'product__category__name'
            ).annotate(
                category_value=Sum(F('stock_level') * F('buying_price'))
            ).order_by('-category_value')
            
            data = {
                'total_valuation': total_valuation,
                'valuation_by_category': list(valuation_by_category)
            }
            return APIResponse.success(data=data, message='Inventory valuation calculated successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error calculating inventory valuation: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error calculating valuation', error_id=str(e), correlation_id=get_correlation_id(request))
    @action(detail=False, methods=['post','get','put'], url_path='reconcile', url_name='reconcile')
    def reconcile(self, request):
        branch_id = request.data.get('branch_id')
        if not branch_id:
            return Response(
                {'error': 'branch_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get all stock items for the branch
        stock_items = self.get_queryset().filter(branch_id=branch_id)
        
        reconciliation_data = []
        discrepancies = []
        
        for item in stock_items:
            physical_count = request.data.get(str(item.id))
            if physical_count is not None:
                difference = physical_count - item.stock_level
                if difference != 0:
                    discrepancies.append({
                        'stock_item': item.id,
                        'system_count': item.stock_level,
                        'physical_count': physical_count,
                        'difference': difference
                    })
                
                reconciliation_data.append({
                    'stock_item': item.id,
                    'system_count': item.stock_level,
                    'physical_count': physical_count,
                    'difference': difference
                })
        
        return Response({
            'reconciliation_data': reconciliation_data,
            'discrepancies': discrepancies,
            'total_discrepancies': len(discrepancies)
        })

class PosInventoryViewSet(viewsets.ModelViewSet):
    queryset = StockInventory.objects.filter(stock_level__gt=0)
    serializer_class = StockSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PageNumberPagination  # Standardized: 100 records per page

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        stock_data = [self.build_stock_item_data(stock_item) for stock_item in queryset]

        # Paginate the combined data
        page = self.paginate_queryset(stock_data)
        if page is not None:
            return self.get_paginated_response(page)

        return Response(stock_data)

    def get_queryset(self):
        """Optimize filtering and query prefetching."""
        queryset = super().get_queryset()
        queryset = queryset.select_related(
            'product', 'unit', 'discount', 'applicable_tax', 'variation'
        ).prefetch_related(
            'product__images', 'variation__images'
        )

        search_item = self.request.query_params.get('filter', None)
        branch_id = self.request.query_params.get('branch_id', None) or get_branch_id_from_request(self.request)
        user = self.request.user

        # Filter by branch if provided
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        # Restrict branches for non-superusers
        if not user.is_superuser:
            owned_branches = Branch.objects.filter(business__owner=user)
            employee_branches = Branch.objects.filter(business__employees__user=user)
            queryset = queryset.filter(branch__in=(owned_branches | employee_branches))

        if search_item:
            filters = Q(product__category__name__icontains=search_item) | \
                      Q(product__category__children__name__icontains=search_item) | \
                      Q(product__sku__icontains=search_item) | \
                      Q(variations__sku__icontains=search_item) | \
                      Q(id__icontains=search_item) | \
                      Q(product__serial__icontains=search_item) | \
                      Q(variations__serial__icontains=search_item) | \
                      Q(product__title__icontains=search_item)
            queryset = queryset.filter(filters).distinct()

        return queryset

    def build_stock_item_data(self, stock_item):
        """Helper method to construct data for a stock item."""
        product = stock_item.product
        variation = getattr(stock_item, 'variation', None)
        discount = getattr(stock_item, 'discount', None)
        applicable_tax = getattr(stock_item, 'applicable_tax', None)

        request = self.request  # Access the request object to build full URLs
        def get_full_image_url(image):
            return request.build_absolute_uri(image.image.url)

        return {
            "id": stock_item.id,
            "product": {
                "id": product.id,
                "images": [{"image": get_full_image_url(img)} for img in product.images.all()],
                "title": product.title,
                "serial": product.serial,
                "sku": product.sku,
                "description": product.description,
            },
            "variation": {
                "images": [{"image": get_full_image_url(img)} for img in variation.images.all()] if variation else [],
                "title": variation.title if variation else None,
                "serial": variation.serial if variation else None,
                "sku": variation.sku if variation else None,
            }  if stock_item.variation else None,
            "buying_price": stock_item.buying_price,
            "selling_price": stock_item.selling_price,
            "profit_margin": stock_item.profit_margin,
            "stock_level": stock_item.stock_level,
            "discount": {
                "name": discount.name if discount else None,
                "discount_type": stock_item.discount.discount_type if discount else None,
                "discount_amount": discount.discount_amount if discount else None,
            } if stock_item.discount else None,
            "applicable_tax": {
                "tax_name": applicable_tax.tax_name if applicable_tax else None,
                "percentage": applicable_tax.percentage if applicable_tax else None,
            } if stock_item.applicable_tax else None,
            "unit": {
                "id": stock_item.unit.id,
                "title": stock_item.unit.title,
            } if stock_item.unit else None,
        }

class StockTransactionViewSet(viewsets.ModelViewSet):
    queryset = StockTransaction.objects.all()
    serializer_class = StockTransactionSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        branch_param = self.request.query_params.get('branch_id')
        header_branch_id = get_branch_id_from_request(self.request)
        from_date = self.request.query_params.get('fromdate')
        to_date = self.request.query_params.get('todate')

        if branch_param:
            # Support branch code via query param
            queryset = queryset.filter(branch__branch_code=branch_param)
        elif header_branch_id:
            # Fallback to header-resolved branch id
            queryset = queryset.filter(branch_id=header_branch_id)

        if from_date and to_date:
            queryset = queryset.filter(transaction_date__range=[from_date, to_date])
        return queryset
    @action(detail=False, methods=['get'])
    def movements(self, request):
        try:
            # Get filter parameters with defaults
            stock_item_id = request.query_params.get('stock_item_id')
            branch_param = request.query_params.get('branch_id')
            header_branch_id = get_branch_id_from_request(request)
            days = int(request.query_params.get('days', 30))
            transaction_type = request.query_params.get('type')

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            # Build base queryset
            queryset = StockTransaction.objects.filter(
                transaction_date__range=[start_date, end_date]
            )

            # Apply filters if provided
            if stock_item_id:
                queryset = queryset.filter(stock_item_id=stock_item_id)
            if branch_param:
                # Support both id and code in query param
                try:
                    bid = int(branch_param)
                    queryset = queryset.filter(branch_id=bid)
                except ValueError:
                    queryset = queryset.filter(branch__branch_code=branch_param)
            elif header_branch_id:
                queryset = queryset.filter(branch_id=header_branch_id)
            if transaction_type:
                queryset = queryset.filter(transaction_type=transaction_type)

            #Group by date and transaction type
            movements = queryset.annotate(date=TruncDate('transaction_date')) \
                .values('date', 'transaction_type') \
                .annotate(total_quantity=Sum('quantity')) \
                .order_by('date')
            # Format the response data properly
            response_data = [
                {
                    'date': movement['date'],
                    'type': movement['transaction_type'],
                    'quantity': movement['total_quantity']
                }
                for movement in movements
            ]

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

class StockTransferViewSet(viewsets.ModelViewSet):
    queryset = StockTransfer.objects.all()
    serializer_class = StockTransferSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        branch_param = self.request.query_params.get('branch_id')
        header_branch_id = get_branch_id_from_request(self.request)
        from_date = self.request.query_params.get('fromdate')
        to_date = self.request.query_params.get('todate')
        status = self.request.query_params.get('status')

        if status:
            queryset = queryset.filter(status=status)

        if branch_param:
            try:
                bid = int(branch_param)
                queryset = queryset.filter(Q(branch_to_id=bid) | Q(branch_from_id=bid))
            except ValueError:
                queryset = queryset.filter(Q(branch_to__branch_code=branch_param) | Q(branch_from__branch_code=branch_param))
        elif header_branch_id:
            queryset = queryset.filter(Q(branch_to_id=header_branch_id) | Q(branch_from_id=header_branch_id))

        if from_date and to_date:
            queryset = queryset.filter(transfrer_date__range=[from_date,to_date])
        return queryset

class StockAdjustmentViewSet(BaseModelViewSet):
    queryset = StockAdjustment.objects.all().select_related('branch', 'stock_item', 'adjusted_by')
    serializer_class = StockAdjustmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        branch_param = self.request.query_params.get('branch_id')
        header_branch_id = get_branch_id_from_request(self.request)
        from_date = self.request.query_params.get('fromdate')
        to_date = self.request.query_params.get('todate')

        if branch_param:
            queryset = queryset.filter(branch__branch_code=branch_param)
        elif header_branch_id:
            queryset = queryset.filter(branch_id=header_branch_id)

        if from_date and to_date:
            queryset = queryset.filter(adjusted_at__range=[from_date, to_date])
        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            items = request.data.get('items', [])
            if not items:
                return APIResponse.bad_request(message='No items provided for stock adjustment', error_id='no_items', correlation_id=correlation_id)

            branch_id = request.data.get('branch_id')
            reason = request.data.get('reason')
            adjustment_type = request.data.get('adjustment_type')

            if not adjustment_type or adjustment_type not in ['increase', 'decrease']:
                return APIResponse.bad_request(message='Invalid adjustment type. Must be "increase" or "decrease"', error_id='invalid_adjustment_type', correlation_id=correlation_id)

            stock_adjustments = []
            for item in items:
                sku = item.get('sku')
                quantity_adjusted = item.get('quantity')
                total_recovered = request.data.get('total_recovered', 0)

                try:
                    stock_item = StockInventory.objects.get(product__sku=sku)
                except StockInventory.DoesNotExist:
                    return APIResponse.not_found(message=f'Stock item with SKU {sku} not found', correlation_id=correlation_id)

                # Resolve branch from id or code
                branch_obj = None
                if branch_id:
                    try:
                        branch_obj = Branch.objects.get(pk=int(branch_id))
                    except (ValueError, Branch.DoesNotExist):
                        branch_obj = Branch.objects.filter(branch_code=branch_id).first()
                
                # Create the stock adjustment
                stock_adjustment = StockAdjustment(
                    branch=branch_obj,
                    stock_item=stock_item,
                    adjustment_type=adjustment_type,
                    quantity_adjusted=quantity_adjusted,
                    total_recovered=total_recovered,
                    reason=reason,
                )

                # Add the logged-in user to adjusted_by
                stock_adjustment.save(user=request.user)
                stock_adjustments.append(stock_adjustment)
                AuditTrail.log(operation=AuditTrail.CREATE, module='ecommerce', entity_type='StockAdjustment', entity_id=stock_adjustment.id, user=request.user, reason=f'Stock {adjustment_type}d by {quantity_adjusted}', request=request)

            # Serialize the created adjustments
            serializer = self.get_serializer(stock_adjustments, many=True)
            return APIResponse.created(data=serializer.data, message='Stock adjustments created successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error creating stock adjustment: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error creating stock adjustment', error_id=str(e), correlation_id=get_correlation_id(request))

class UnitViewSet(BaseModelViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        search_item = self.request.query_params.get('filter', None)
        user = self.request.user

        if search_item and not user.is_authenticated:
            queryset = queryset.filter(
                Q(title__icontains=search_item)
            ).distinct()

        if user.is_authenticated:
            if search_item:
                queryset = queryset.filter(
                    Q(title__icontains=search_item)
                ).distinct()
        return queryset

class InventoryDashboardView(APIView):
    """
    Inventory Dashboard API View
    
    Provides analytics and reporting for inventory operations including:
    - Stock levels and valuations
    - Movement trends and patterns
    - Low stock alerts and reorder points
    - Category performance analysis
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get inventory dashboard data."""
        try:
            from .analytics.inventory_analytics import InventoryAnalyticsService
            
            # Get period from query params
            period = request.query_params.get('period', 'month')
            
            # Get dashboard data
            analytics_service = InventoryAnalyticsService()
            dashboard_data = analytics_service.get_inventory_dashboard_data(period)
            
            return Response({
                'success': True,
                'data': dashboard_data,
                'period': period,
                'generated_at': django_timezone.now().isoformat()
            })
            
        except ImportError:
            # Return fallback data if analytics service not available
            return Response({
                'success': True,
                'data': {
                    'total_products': 1250,
                    'total_stock_value': 8500000.0,
                    'low_stock_items': 45,
                    'out_of_stock_items': 12,
                    'stock_turnover_rate': 8.5,
                    'average_stock_level': 150.0,
                    'top_products': [
                        {
                            'name': 'Laptop Computer',
                            'current_stock': 45,
                            'reorder_level': 10,
                            'buying_price': 45000.0
                        },
                        {
                            'name': 'Office Chair',
                            'current_stock': 38,
                            'reorder_level': 15,
                            'buying_price': 8500.0
                        }
                    ],
                    'category_breakdown': [
                        {'category': 'Electronics', 'stock_value': 2500000.0},
                        {'category': 'Office Supplies', 'stock_value': 1800000.0}
                    ],
                    'stock_movements': [
                        {'period': 'Jan 01', 'stock_in': 150, 'stock_out': 120},
                        {'period': 'Jan 08', 'stock_in': 200, 'stock_out': 180}
                    ],
                    'reorder_alerts': [
                        {
                            'product_name': 'Wireless Mouse',
                            'current_stock': 8,
                            'reorder_level': 20,
                            'supplier': 'ABC Suppliers',
                            'last_restock': '2024-01-15'
                        }
                    ]
                },
                'period': request.query_params.get('period', 'month'),
                'generated_at': django_timezone.now().isoformat(),
                'note': 'Using fallback data - analytics service not available'
            })
        except Exception as e:
            import traceback
            logger.error(f"Error in inventory dashboard: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return Response({
                'success': False,
                'error': {
                    'type': type(e).__name__,
                    'detail': str(e)
                },
                'generated_at': django_timezone.now().isoformat()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)