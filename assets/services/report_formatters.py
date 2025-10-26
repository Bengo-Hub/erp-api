"""
Assets Report Formatters Service

Modular components for generating asset management and depreciation reports.
Each report type is a single-responsibility class for maintainability and reusability.

Reports Generated:
- Inventory Report
- Depreciation Report
"""

import polars as pl
from decimal import Decimal
from typing import Dict, List, Any, Optional
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class InventoryReport:
    """Asset Inventory Report - Stock levels and valuations."""

    COLUMNS = [
        {'field': 'asset_name', 'header': 'Asset Name'},
        {'field': 'category', 'header': 'Category'},
        {'field': 'acquisition_cost', 'header': 'Acquisition Cost (KShs)'},
        {'field': 'accumulated_depreciation', 'header': 'Accumulated Depreciation (KShs)'},
        {'field': 'book_value', 'header': 'Book Value (KShs)'},
        {'field': 'status', 'header': 'Status'},
    ]

    @staticmethod
    def build(business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build Asset Inventory Report.

        Args:
            business_id: Optional business filter

        Returns:
            Dict with asset data and valuations
        """
        try:
            inventory_data = []

            # TODO: Query assets and aggregate valuations
            # This will be populated when asset models are fully integrated

            df = pl.DataFrame(inventory_data) if inventory_data else pl.DataFrame([])

            return {
                'report_type': 'Asset Inventory',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': InventoryReport.COLUMNS,
                'title': 'Assets Inventory Report',
                'totals': {
                    'total_assets': len(df),
                    'total_acquisition_cost': 0.0,
                    'total_book_value': 0.0,
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Asset Inventory Report: {str(e)}", exc_info=True)
            return {
                'report_type': 'Asset Inventory',
                'error': str(e),
                'data': [],
                'columns': InventoryReport.COLUMNS,
            }


class DepreciationReport:
    """Depreciation Report - Depreciation schedules and accumulated values."""

    COLUMNS = [
        {'field': 'asset_name', 'header': 'Asset Name'},
        {'field': 'category', 'header': 'Category'},
        {'field': 'acquisition_cost', 'header': 'Acquisition Cost (KShs)'},
        {'field': 'depreciation_method', 'header': 'Method'},
        {'field': 'annual_depreciation', 'header': 'Annual Depreciation (KShs)'},
        {'field': 'accumulated_depreciation', 'header': 'Accumulated (KShs)'},
        {'field': 'remaining_life', 'header': 'Remaining Life (years)'},
    ]

    @staticmethod
    def build(business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build Depreciation Report.

        Args:
            business_id: Optional business filter

        Returns:
            Dict with depreciation schedules and projections
        """
        try:
            depreciation_data = []

            # TODO: Query asset depreciation records and calculate schedules
            # This will be populated when asset depreciation models are fully integrated

            df = pl.DataFrame(depreciation_data) if depreciation_data else pl.DataFrame([])

            return {
                'report_type': 'Depreciation Report',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': DepreciationReport.COLUMNS,
                'title': 'Assets Depreciation Report',
                'totals': {
                    'total_depreciation': 0.0,
                    'total_accumulated': 0.0,
                    'assets_with_depreciation': 0,
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Depreciation Report: {str(e)}", exc_info=True)
            return {
                'report_type': 'Depreciation Report',
                'error': str(e),
                'data': [],
                'columns': DepreciationReport.COLUMNS,
            }


class AssetsReportFormatter:
    """Main Assets Report Formatter - Orchestrates all reports."""

    @staticmethod
    def generate_inventory_report(business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate Inventory Report."""
        return InventoryReport.build(business_id)

    @staticmethod
    def generate_depreciation_report(business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate Depreciation Report."""
        return DepreciationReport.build(business_id)
