"""
Core Analytics Services Module

This module provides centralized analytics and reporting services for the ERP system.
It aggregates data from various modules and provides unified dashboard endpoints.

SharedAnalyticsService provides common analytics utilities used across all modules
to ensure consistent calculations between executive dashboard, finance dashboard,
and any other reports or analytics.
"""

from .executive_analytics import ExecutiveAnalyticsService
from .performance_analytics import PerformanceAnalyticsService
from .shared_analytics import SharedAnalyticsService

__all__ = [
    'ExecutiveAnalyticsService',
    'PerformanceAnalyticsService',
    'SharedAnalyticsService',
]
