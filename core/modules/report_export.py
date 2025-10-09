import polars as pl
from django.http import HttpResponse

def export_report_to_csv(data, filename='report.csv'):
    """
    Export a list of dicts or a polars DataFrame to CSV as a Django HttpResponse.
    """
    if not isinstance(data, pl.DataFrame):
        df = pl.DataFrame(data)
    else:
        df = data
    csv_bytes = df.write_csv()
    response = HttpResponse(csv_bytes, content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def export_report_to_pdf(data, filename='report.pdf'):
    """
    Placeholder for PDF export. Implement using reportlab, weasyprint, or similar.
    """
    return HttpResponse('PDF export not implemented', status=501)

# Usage:
# from core.modules.report_export import export_report_to_csv, export_report_to_pdf
# return export_report_to_csv(data, filename='my_report.csv') 