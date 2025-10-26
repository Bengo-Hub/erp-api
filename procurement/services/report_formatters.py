"""
Procurement Report Formatters Service

Modular components for generating procurement analytics and supplier performance reports.
Each report type is a single-responsibility class for maintainability and reusability.

Reports Generated:
- Supplier Analysis
- Spend Analysis
"""

import polars as pl
from decimal import Decimal
from typing import Dict, List, Any, Optional
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class SupplierAnalysisReport:
    """Supplier Analysis - Performance and cost metrics."""

    COLUMNS = [
        {'field': 'supplier_name', 'header': 'Supplier Name'},
        {'field': 'total_orders', 'header': 'Total Orders'},
        {'field': 'total_spend', 'header': 'Total Spend (KShs)'},
        {'field': 'avg_order_value', 'header': 'Avg Order Value (KShs)'},
        {'field': 'delivery_rating', 'header': 'Delivery Rating'},
        {'field': 'quality_rating', 'header': 'Quality Rating'},
    ]

    @staticmethod
    def build(business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build Supplier Analysis report.

        Args:
            business_id: Optional business filter

        Returns:
            Dict with supplier data and metrics
        """
        try:
            supplier_data = []

            # TODO: Query suppliers and aggregate metrics
            # This will be populated when supplier model integration is complete

            df = pl.DataFrame(supplier_data) if supplier_data else pl.DataFrame([])

            return {
                'report_type': 'Supplier Analysis',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': SupplierAnalysisReport.COLUMNS,
                'title': 'Procurement Supplier Analysis',
                'totals': {
                    'total_suppliers': len(df),
                    'total_spend': 0.0,
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Supplier Analysis: {str(e)}", exc_info=True)
            return {
                'report_type': 'Supplier Analysis',
                'error': str(e),
                'data': [],
                'columns': SupplierAnalysisReport.COLUMNS,
            }


class SpendAnalysisReport:
    """Spend Analysis - Category breakdown and trends."""

    COLUMNS = [
        {'field': 'category', 'header': 'Category'},
        {'field': 'total_spend', 'header': 'Total Spend (KShs)'},
        {'field': 'percentage', 'header': 'Percentage %'},
        {'field': 'order_count', 'header': 'Order Count'},
        {'field': 'trend', 'header': 'Trend'},
    ]

    @staticmethod
    def build(business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build Spend Analysis report.

        Args:
            business_id: Optional business filter

        Returns:
            Dict with spend data by category
        """
        try:
            spend_data = []

            # TODO: Query purchase orders and aggregate by category
            # This will be populated when procurement models are fully integrated

            df = pl.DataFrame(spend_data) if spend_data else pl.DataFrame([])

            return {
                'report_type': 'Spend Analysis',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': SpendAnalysisReport.COLUMNS,
                'title': 'Procurement Spend Analysis',
                'totals': {
                    'total_spend': 0.0,
                    'categories': 0,
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Spend Analysis: {str(e)}", exc_info=True)
            return {
                'report_type': 'Spend Analysis',
                'error': str(e),
                'data': [],
                'columns': SpendAnalysisReport.COLUMNS,
            }


class ProcurementReportFormatter:
    """Main Procurement Report Formatter - Orchestrates all reports."""

    @staticmethod
    def generate_supplier_analysis(business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate Supplier Analysis report."""
        return SupplierAnalysisReport.build(business_id)

    @staticmethod
    def generate_spend_analysis(business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate Spend Analysis report."""
        return SpendAnalysisReport.build(business_id)
