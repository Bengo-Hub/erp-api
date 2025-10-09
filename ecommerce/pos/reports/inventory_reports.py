from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum,Count,F
from django.utils import timezone
from datetime import timedelta
from ecommerce.stockinventory.models import StockInventory

class StockReports(APIView):
    def get(self, request, *args, **kwargs):
        report_type= request.query_params.get('report_type', 'None')
        # 1. Stock Level and Turnover Report
        stock_level_and_turnover = StockInventory.objects.annotate(
            total_sold=Count('salesitems'),
            turnover=F('total_sold') / F('stock_level'),
        ).values('product__title','size__size', 'size__unit__unit_title', 'stock_level', 'total_sold', 'turnover')

        # 2. Products Nearing Stock-Out Report
        products_nearing_stock_out = StockInventory.objects.filter(
            stock_level__lte=F('reorder_level')
        ).values('product__title','size__size', 'size__unit__unit_title','stock_level', 'reorder_level')

        return Response({
            'stock_level_and_turnover': stock_level_and_turnover,
            'products_nearing_stock_out': products_nearing_stock_out
        })
