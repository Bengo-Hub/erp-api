"""
Executive Analytics Service

Provides high-level business intelligence by aggregating data from all ERP modules.
This service is used by the Executive Dashboard to show KPIs and trends.

Uses SharedAnalyticsService for consistent calculations across all dashboards.
"""

from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Sum, Count, Q, Avg
from django.db.models.functions import TruncDate, TruncMonth
from decimal import Decimal
import logging

from core.analytics.shared_analytics import SharedAnalyticsService

logger = logging.getLogger(__name__)


class ExecutiveAnalyticsService:
    """
    Service for executive-level analytics and business intelligence.
    Aggregates data from finance, sales, HRM, procurement, manufacturing, and inventory modules.
    """
    
    def __init__(self):
        self.default_periods = {
            'week': 7,
            'month': 30,
            'quarter': 90,
            'year': 365
        }
    
    def get_executive_dashboard_data(self, period='month', business_id=None, branch_id=None):
        """
        Get comprehensive executive dashboard data.
        
        Args:
            period (str): Time period for analysis ('week', 'month', 'quarter', 'year')
            business_id (int): Business ID to filter data
            branch_id (int): Branch ID to filter data
            
        Returns:
            dict: Aggregated dashboard data with fallbacks for missing data
        """
        try:
            days = self.default_periods.get(period, 30)
            start_date = timezone.now().date() - timedelta(days=days)
            end_date = timezone.now().date()
            
            # Get data from various modules with safe fallbacks
            financial_data = self._get_financial_metrics(start_date, end_date, business_id, branch_id)
            operational_data = self._get_operational_metrics(start_date, end_date, business_id, branch_id)
            performance_data = self._get_performance_metrics(start_date, end_date, business_id, branch_id)
            trend_data = self._get_trend_data(start_date, end_date, business_id, branch_id)
            
            return {
                # Financial KPIs
                'total_revenue': financial_data.get('total_revenue', 0),
                'total_expenses': financial_data.get('total_expenses', 0),
                'net_profit': financial_data.get('net_profit', 0),
                'profit_margin': financial_data.get('profit_margin', 0),
                
                # Operational KPIs
                'total_orders': operational_data.get('total_orders', 0),
                'total_customers': operational_data.get('total_customers', 0),
                'total_employees': operational_data.get('total_employees', 0),
                'total_suppliers': operational_data.get('total_suppliers', 0),
                
                # Performance metrics
                'order_fulfillment_rate': performance_data.get('order_fulfillment_rate', 0),
                'customer_satisfaction': performance_data.get('customer_satisfaction', 0),
                'employee_productivity': performance_data.get('employee_productivity', 0),
                'inventory_turnover': performance_data.get('inventory_turnover', 0),
                
                # Trends
                'revenue_trends': trend_data.get('revenue_trends', []),
                'profit_trends': trend_data.get('profit_trends', []),
                'order_trends': trend_data.get('order_trends', []),
                'customer_growth': trend_data.get('customer_growth', [])
            }
            
        except Exception as e:
            logger.error(f"Error in get_executive_dashboard_data: {e}")
            # Return safe fallback data if any errors occur
            return self._get_fallback_data()
    
    def _get_financial_metrics(self, start_date, end_date, business_id=None, branch_id=None):
        """Get financial metrics using shared analytics service for consistency."""
        try:
            # Use shared analytics for consistent calculations across dashboards
            return SharedAnalyticsService.get_financial_summary(start_date, end_date, business_id)

        except Exception as e:
            logger.error(f"Error getting financial metrics: {e}")
            return {
                'total_revenue': 0.0,
                'total_expenses': 0.0,
                'net_profit': 0.0,
                'profit_margin': 0.0
            }
    
    def _get_operational_metrics(self, start_date, end_date, business_id=None, branch_id=None):
        """Get operational metrics using shared analytics service for consistency."""
        try:
            return {
                'total_orders': SharedAnalyticsService.get_order_count(start_date, end_date, business_id),
                'total_customers': SharedAnalyticsService.get_customer_count(business_id=business_id, new_only=True),
                'total_employees': SharedAnalyticsService.get_employee_count(business_id),
                'total_suppliers': SharedAnalyticsService.get_supplier_count(business_id)
            }

        except Exception as e:
            logger.error(f"Error getting operational metrics: {e}")
            return {
                'total_orders': 0,
                'total_customers': 0,
                'total_employees': 0,
                'total_suppliers': 0
            }
    
    def _get_performance_metrics(self, start_date, end_date, business_id=None, branch_id=None):
        """Get performance metrics using shared analytics service for consistency."""
        try:
            fulfillment_rate = SharedAnalyticsService.get_order_fulfillment_rate(start_date, end_date, business_id)

            # Inventory turnover (calculate from real data if possible)
            inventory_turnover = 0
            try:
                from ecommerce.stockinventory.models import StockInventory
                total_orders = SharedAnalyticsService.get_order_count(start_date, end_date, business_id)
                total_inventory = StockInventory.objects.filter(
                    available_quantity__gt=0
                ).count()
                if total_inventory > 0 and total_orders > 0:
                    inventory_turnover = round(total_orders / total_inventory, 2)
            except Exception:
                pass

            return {
                'order_fulfillment_rate': float(fulfillment_rate),
                'customer_satisfaction': 0,  # Not yet implemented
                'employee_productivity': 0,  # Not yet implemented
                'inventory_turnover': float(inventory_turnover)
            }

        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            return {
                'order_fulfillment_rate': 0,
                'customer_satisfaction': 0,
                'employee_productivity': 0,
                'inventory_turnover': 0
            }
    
    def _get_trend_data(self, start_date, end_date, business_id=None, branch_id=None):
        """Get trend data for charts using shared analytics service for consistency."""
        try:
            return {
                'revenue_trends': SharedAnalyticsService.get_revenue_trends(start_date, end_date, business_id),
                'profit_trends': SharedAnalyticsService.get_profit_trends(start_date, end_date, business_id),
                'order_trends': SharedAnalyticsService.get_order_trends(start_date, end_date, business_id),
                'customer_growth': SharedAnalyticsService.get_customer_growth(start_date, end_date, business_id)
            }

        except Exception as e:
            logger.error(f"Error getting trend data: {e}")
            return self._get_empty_trend_data()
    
    def _get_empty_trend_data(self):
        """Return empty trend data arrays when no data is available."""
        return {
            'revenue_trends': [],
            'profit_trends': [],
            'order_trends': [],
            'customer_growth': []
        }
    
    def _get_fallback_data(self):
        """Return empty/zero fallback data for the dashboard when data retrieval fails."""
        return {
            'total_revenue': 0.0,
            'total_expenses': 0.0,
            'net_profit': 0.0,
            'profit_margin': 0.0,
            'total_orders': 0,
            'total_customers': 0,
            'total_employees': 0,
            'total_suppliers': 0,
            'order_fulfillment_rate': 0,
            'customer_satisfaction': 0,
            'employee_productivity': 0,
            'inventory_turnover': 0,
            'revenue_trends': [],
            'profit_trends': [],
            'order_trends': [],
            'customer_growth': []
        }
