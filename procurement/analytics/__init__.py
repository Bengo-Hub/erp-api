"""
Procurement Analytics Services Module

This module provides analytics and reporting services for the procurement module.
It aggregates data from purchase orders, requisitions, and supplier performance.
"""

from .procurement_analytics import ProcurementAnalyticsService

__all__ = [
    'ProcurementAnalyticsService',
]
