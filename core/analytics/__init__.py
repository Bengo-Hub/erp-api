"""
Core Analytics Services Module

This module provides centralized analytics and reporting services for the ERP system.
It aggregates data from various modules and provides unified dashboard endpoints.
"""

from .executive_analytics import ExecutiveAnalyticsService
from .performance_analytics import PerformanceAnalyticsService

__all__ = [
    'ExecutiveAnalyticsService',
    'PerformanceAnalyticsService',
]
