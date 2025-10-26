from django.db.models import Sum, Count
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from ecommerce.pos.serializers import SalesSerializer,SalesItemsSerializer
from ecommerce.pos.models import Sales,salesItems
from django.utils import timezone
from datetime import timedelta
import polars as pl
from django.http import HttpResponse
from ecommerce.pos.services import POSReportService
from core.modules.report_export import export_report_to_csv, export_report_to_pdf

class SalesSummaryReport(APIView):
    def get(self, request, *args, **kwargs):
        # Use the service to get report data
        data = POSReportService.get_sales_summary(request)
        # Optionally, export to CSV or PDF if requested
        export_format = request.query_params.get('export')
        if export_format == 'csv':
            return export_report_to_csv(data, filename='sales_summary.csv')
        elif export_format == 'pdf':
            return export_report_to_pdf(data, filename='sales_summary.pdf')
        return Response(data)

def export_report_to_csv(data, filename='report.csv'):
    # Deprecated local implementation; use centralized export
    return export_report_to_csv(data, filename)

def export_report_to_pdf(data, filename='report.pdf'):
    # Deprecated local implementation; use centralized export
    return export_report_to_pdf(data, filename)
