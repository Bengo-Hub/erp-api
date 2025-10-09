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
    df = pl.DataFrame(data)
    csv_bytes = df.write_csv()
    response = HttpResponse(csv_bytes, content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def export_report_to_pdf(data, filename='report.pdf'):
    # Placeholder: implement PDF export using a library like reportlab or weasyprint
    # For now, just return a not implemented response
    return HttpResponse('PDF export not implemented', status=501)
