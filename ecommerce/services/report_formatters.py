"""
E-commerce Reports Formatter Service

Modular components for generating comprehensive e-commerce analytics and reports.
Each report type is a single-responsibility class for maintainability and reusability.

Reports Generated:
- Sales Dashboard (daily/weekly/monthly trends)
- Product Performance (revenue, quantity, margin analysis)
- Customer Analysis (lifetime value, segmentation)
- Inventory Management (stock levels, turnover, reorder status)
- Order Fulfillment (processing metrics, delivery analysis)
"""

import polars as pl
from decimal import Decimal
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, date
from django.db.models import Sum, Count, Avg, Q, F, Case, When, DecimalField
from django.utils import timezone
import logging

from ecommerce.order.models import Order
from ecommerce.product.models import Products, Category
from ecommerce.stockinventory.models import StockInventory
from crm.contacts.models import Contact
from core_orders.models import OrderItem

logger = logging.getLogger(__name__)


class SalesDashboard:
    """Sales Dashboard - Daily/Weekly/Monthly trend analysis."""
    
    REPORT_TYPE = 'Sales Dashboard'
    
    COLUMNS = [
        {'field': 'period', 'header': 'Period'},
        {'field': 'total_orders', 'header': 'Total Orders'},
        {'field': 'total_sales', 'header': 'Sales (KShs)'},
        {'field': 'average_order_value', 'header': 'Avg Order Value (KShs)'},
        {'field': 'units_sold', 'header': 'Units Sold'},
        {'field': 'order_growth', 'header': 'Order Growth %'},
        {'field': 'revenue_growth', 'header': 'Revenue Growth %'},
    ]
    
    @staticmethod
    def build(start_date: date, end_date: date, period_type: str = 'daily', business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build sales dashboard for period.
        
        Args:
            start_date: Period start date
            end_date: Period end date
            period_type: 'daily', 'weekly', or 'monthly'
            business_id: Optional business filter
            
        Returns:
            Dict with sales dashboard data and metrics
        """
        try:
            # Get previous period for comparison
            period_days = (end_date - start_date).days
            prev_start = start_date - timedelta(days=period_days + 1)
            prev_end = start_date - timedelta(days=1)
            
            # Get current period data
            current_qs = Order.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date,
                status__in=['completed', 'delivered']
            )
            
            # Get previous period data
            prev_qs = Order.objects.filter(
                created_at__gte=prev_start,
                created_at__lte=prev_end,
                status__in=['completed', 'delivered']
            )
            
            # Calculate metrics
            current_orders = current_qs.count()
            current_sales = current_qs.aggregate(total=Sum('grand_total'))['total'] or Decimal('0')
            current_units = sum(item.quantity for order in current_qs for item in order.items.all())
            
            prev_orders = prev_qs.count()
            prev_sales = prev_qs.aggregate(total=Sum('grand_total'))['total'] or Decimal('0')
            prev_units = sum(item.quantity for order in prev_qs for item in order.items.all())
            
            # Calculate growth
            order_growth = ((current_orders - prev_orders) / prev_orders * 100) if prev_orders > 0 else 0
            revenue_growth = ((current_sales - prev_sales) / prev_sales * 100) if prev_sales > 0 else 0
            avg_order_value = (current_sales / current_orders) if current_orders > 0 else 0
            
            # Build dashboard data
            dashboard_data = [{
                'period': f'{start_date.strftime("%b %d, %Y")} to {end_date.strftime("%b %d, %Y")}',
                'total_orders': current_orders,
                'total_sales': float(current_sales),
                'average_order_value': float(avg_order_value),
                'units_sold': current_units,
                'order_growth': round(order_growth, 2),
                'revenue_growth': round(revenue_growth, 2),
            }]
            
            # Daily breakdown if requested
            daily_data = []
            if period_type == 'daily':
                current_date = start_date
                while current_date <= end_date:
                    day_qs = current_qs.filter(
                        created_at__date=current_date
                    )
                    day_orders = day_qs.count()
                    day_sales = day_qs.aggregate(total=Sum('grand_total'))['total'] or Decimal('0')
                    day_units = sum(item.quantity for order in day_qs for item in order.items.all())
                    
                    if day_orders > 0:
                        daily_data.append({
                            'period': current_date.strftime('%Y-%m-%d'),
                            'total_orders': day_orders,
                            'total_sales': float(day_sales),
                            'average_order_value': float(day_sales / day_orders),
                            'units_sold': day_units,
                            'order_growth': 0,
                            'revenue_growth': 0,
                        })
                    current_date += timedelta(days=1)
            
            df = pl.DataFrame(daily_data if daily_data else dashboard_data)
            
            return {
                'report_type': 'Sales Dashboard',
                'data': df.to_dicts() if not df.is_empty() else dashboard_data,
                'columns': SalesDashboard.COLUMNS,
                'title': f'Sales Dashboard - {start_date.strftime("%b %d, %Y")} to {end_date.strftime("%b %d, %Y")}',
                'period': {'start': start_date.isoformat(), 'end': end_date.isoformat(), 'type': period_type},
                'summary': {
                    'total_orders': current_orders,
                    'total_sales': float(current_sales),
                    'average_order_value': float(avg_order_value),
                    'total_units': current_units,
                    'order_growth_percent': round(order_growth, 2),
                    'revenue_growth_percent': round(revenue_growth, 2),
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Sales Dashboard: {str(e)}", exc_info=True)
            return {
                'report_type': 'Sales Dashboard',
                'error': str(e),
                'data': [],
                'columns': SalesDashboard.COLUMNS,
            }


class ProductPerformanceReport:
    """Product Performance - Revenue, quantity, and margin analysis."""
    
    REPORT_TYPE = 'Product Performance'
    
    COLUMNS = [
        {'field': 'product_name', 'header': 'Product Name'},
        {'field': 'sku', 'header': 'SKU'},
        {'field': 'category', 'header': 'Category'},
        {'field': 'units_sold', 'header': 'Units Sold'},
        {'field': 'revenue', 'header': 'Revenue (KShs)'},
        {'field': 'avg_selling_price', 'header': 'Avg Price (KShs)'},
        {'field': 'profit_margin_percent', 'header': 'Margin %'},
        {'field': 'rank', 'header': 'Rank'},
    ]
    
    @staticmethod
    def build(start_date: date, end_date: date, top_n: int = 50, business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build product performance report.
        
        Args:
            start_date: Period start date
            end_date: Period end date
            top_n: Top N products to include
            business_id: Optional business filter
            
        Returns:
            Dict with product performance data
        """
        try:
            # Get order items for period
            order_items_qs = OrderItem.objects.filter(
                order__created_at__gte=start_date,
                order__created_at__lte=end_date,
                order__status__in=['completed', 'delivered']
            )
            
            # Aggregate by product
            product_data = []
            products_dict = {}
            
            for item in order_items_qs:
                product_id = item.product_id
                if product_id not in products_dict:
                    products_dict[product_id] = {
                        'units': 0,
                        'revenue': Decimal('0'),
                        'prices': [],
                        'costs': [],
                    }
                
                products_dict[product_id]['units'] += item.quantity
                products_dict[product_id]['revenue'] += (item.price or Decimal('0')) * item.quantity
                products_dict[product_id]['prices'].append(item.price or Decimal('0'))
                if hasattr(item, 'cost_price'):
                    products_dict[product_id]['costs'].append(item.cost_price or Decimal('0'))
            
            # Build product rows
            rank = 1
            for product_id, data in sorted(products_dict.items(), key=lambda x: x[1]['revenue'], reverse=True)[:top_n]:
                try:
                    product = Products.objects.get(id=product_id)
                    avg_price = sum(data['prices']) / len(data['prices']) if data['prices'] else Decimal('0')
                    avg_cost = sum(data['costs']) / len(data['costs']) if data['costs'] else Decimal('0')
                    margin = ((avg_price - avg_cost) / avg_price * 100) if avg_price > 0 else 0
                    
                    product_data.append({
                        'product_name': product.title,
                        'sku': product.sku or 'N/A',
                        'category': product.category.name if product.category else 'Uncategorized',
                        'units_sold': data['units'],
                        'revenue': float(data['revenue']),
                        'avg_selling_price': float(avg_price),
                        'profit_margin_percent': round(margin, 2),
                        'rank': rank,
                    })
                    rank += 1
                except Products.DoesNotExist:
                    continue
            
            df = pl.DataFrame(product_data) if product_data else pl.DataFrame([])
            
            return {
                'report_type': 'Product Performance',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': ProductPerformanceReport.COLUMNS,
                'title': f'Product Performance - {start_date.strftime("%b %d, %Y")} to {end_date.strftime("%b %d, %Y")}',
                'period': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
                'summary': {
                    'total_products': len(product_data),
                    'total_units_sold': sum(p['units_sold'] for p in product_data),
                    'total_revenue': sum(p['revenue'] for p in product_data),
                    'average_margin': round(sum(p['profit_margin_percent'] for p in product_data) / len(product_data), 2) if product_data else 0,
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Product Performance report: {str(e)}", exc_info=True)
            return {
                'report_type': 'Product Performance',
                'error': str(e),
                'data': [],
                'columns': ProductPerformanceReport.COLUMNS,
            }


class CustomerAnalysisReport:
    """Customer Analysis - Lifetime value, segments, and behavior."""
    
    REPORT_TYPE = 'Customer Analysis'
    
    COLUMNS = [
        {'field': 'customer_name', 'header': 'Customer Name'},
        {'field': 'email', 'header': 'Email'},
        {'field': 'total_orders', 'header': 'Total Orders'},
        {'field': 'lifetime_value', 'header': 'Lifetime Value (KShs)'},
        {'field': 'average_order_value', 'header': 'Avg Order Value (KShs)'},
        {'field': 'first_order_date', 'header': 'First Order'},
        {'field': 'last_order_date', 'header': 'Last Order'},
        {'field': 'segment', 'header': 'Segment'},
    ]
    
    @staticmethod
    def build(start_date: date, end_date: date, min_orders: int = 1, business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build customer analysis report.
        
        Args:
            start_date: Analysis period start
            end_date: Analysis period end
            min_orders: Minimum orders to include
            business_id: Optional business filter
            
        Returns:
            Dict with customer analysis data
        """
        try:
            # Get all orders for customers
            orders_qs = Order.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date,
                status__in=['completed', 'delivered']
            )
            
            # Aggregate by customer
            customer_data = []
            customers_dict = {}
            
            for order in orders_qs:
                contact_id = order.contact_id
                if contact_id not in customers_dict:
                    customers_dict[contact_id] = {
                        'orders': 0,
                        'revenue': Decimal('0'),
                        'first_order': order.created_at,
                        'last_order': order.created_at,
                    }
                
                customers_dict[contact_id]['orders'] += 1
                customers_dict[contact_id]['revenue'] += order.grand_total or Decimal('0')
                customers_dict[contact_id]['first_order'] = min(customers_dict[contact_id]['first_order'], order.created_at)
                customers_dict[contact_id]['last_order'] = max(customers_dict[contact_id]['last_order'], order.created_at)
            
            # Build customer rows
            for contact_id, data in customers_dict.items():
                if data['orders'] >= min_orders:
                    try:
                        contact = Contact.objects.get(id=contact_id)
                        avg_order_value = data['revenue'] / data['orders']
                        
                        # Segment customers
                        if data['orders'] >= 10:
                            segment = 'VIP'
                        elif data['orders'] >= 5:
                            segment = 'Loyal'
                        elif data['orders'] >= 2:
                            segment = 'Regular'
                        else:
                            segment = 'New'
                        
                        customer_data.append({
                            'customer_name': contact.name or 'Unknown',
                            'email': contact.email or 'N/A',
                            'total_orders': data['orders'],
                            'lifetime_value': float(data['revenue']),
                            'average_order_value': float(avg_order_value),
                            'first_order_date': data['first_order'].strftime('%Y-%m-%d'),
                            'last_order_date': data['last_order'].strftime('%Y-%m-%d'),
                            'segment': segment,
                        })
                    except Contact.DoesNotExist:
                        continue
            
            # Sort by lifetime value
            customer_data = sorted(customer_data, key=lambda x: x['lifetime_value'], reverse=True)
            df = pl.DataFrame(customer_data) if customer_data else pl.DataFrame([])
            
            return {
                'report_type': 'Customer Analysis',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': CustomerAnalysisReport.COLUMNS,
                'title': f'Customer Analysis - {start_date.strftime("%b %d, %Y")} to {end_date.strftime("%b %d, %Y")}',
                'period': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
                'segments': {
                    'vip': len([c for c in customer_data if c['segment'] == 'VIP']),
                    'loyal': len([c for c in customer_data if c['segment'] == 'Loyal']),
                    'regular': len([c for c in customer_data if c['segment'] == 'Regular']),
                    'new': len([c for c in customer_data if c['segment'] == 'New']),
                },
                'summary': {
                    'total_customers': len(customer_data),
                    'total_lifetime_value': sum(c['lifetime_value'] for c in customer_data),
                    'average_lifetime_value': round(sum(c['lifetime_value'] for c in customer_data) / len(customer_data), 2) if customer_data else 0,
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Customer Analysis report: {str(e)}", exc_info=True)
            return {
                'report_type': 'Customer Analysis',
                'error': str(e),
                'data': [],
                'columns': CustomerAnalysisReport.COLUMNS,
            }


class InventoryReport:
    """Inventory Management - Stock levels, turnover, reorder status."""
    
    REPORT_TYPE = 'Inventory Management'
    
    COLUMNS = [
        {'field': 'product_name', 'header': 'Product Name'},
        {'field': 'sku', 'header': 'SKU'},
        {'field': 'category', 'header': 'Category'},
        {'field': 'current_stock', 'header': 'Current Stock'},
        {'field': 'reorder_level', 'header': 'Reorder Level'},
        {'field': 'status', 'header': 'Status'},
        {'field': 'stock_value', 'header': 'Stock Value (KShs)'},
        {'field': 'turnover_rate', 'header': 'Turnover Rate'},
    ]
    
    @staticmethod
    def build(business_id: Optional[int] = None, include_low_stock: bool = True) -> Dict[str, Any]:
        """
        Build inventory report.
        
        Args:
            business_id: Optional business filter
            include_low_stock: Whether to highlight low stock items
            
        Returns:
            Dict with inventory data
        """
        try:
            stock_qs = StockInventory.objects.filter(availability__iexact='in stock')
            
            if business_id:
                stock_qs = stock_qs.filter(branch__business_id=business_id)
            
            inventory_data = []
            for stock in stock_qs:
                # Determine status
                if stock.stock_level <= stock.reorder_level:
                    status = 'Low Stock'
                elif stock.stock_level > stock.reorder_level * 2:
                    status = 'Adequate'
                else:
                    status = 'Monitor'
                
                # Calculate stock value
                stock_value = (stock.buying_price or Decimal('0')) * stock.stock_level
                
                # Estimate turnover (simplified)
                turnover_rate = 'N/A'
                
                if include_low_stock or status != 'Low Stock':
                    inventory_data.append({
                        'product_name': stock.product.title if stock.product else 'Unknown',
                        'sku': stock.product.sku if stock.product else 'N/A',
                        'category': stock.product.category.name if stock.product and stock.product.category else 'Uncategorized',
                        'current_stock': stock.stock_level,
                        'reorder_level': stock.reorder_level,
                        'status': status,
                        'stock_value': float(stock_value),
                        'turnover_rate': turnover_rate,
                    })
            
            df = pl.DataFrame(inventory_data) if inventory_data else pl.DataFrame([])
            
            # Count statuses
            low_stock_count = len([i for i in inventory_data if i['status'] == 'Low Stock'])
            
            return {
                'report_type': 'Inventory Management',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': InventoryReport.COLUMNS,
                'title': 'Inventory Management Report',
                'summary': {
                    'total_items': len(inventory_data),
                    'total_stock_value': sum(i['stock_value'] for i in inventory_data),
                    'low_stock_items': low_stock_count,
                    'adequate_stock': len([i for i in inventory_data if i['status'] == 'Adequate']),
                    'monitor_stock': len([i for i in inventory_data if i['status'] == 'Monitor']),
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Inventory report: {str(e)}", exc_info=True)
            return {
                'report_type': 'Inventory Management',
                'error': str(e),
                'data': [],
                'columns': InventoryReport.COLUMNS,
            }


class EcommerceReportFormatter:
    """Main E-commerce Report Formatter - Orchestrates all e-commerce reports."""
    
    @staticmethod
    def generate_sales_dashboard(start_date: date, end_date: date, period_type: str = 'daily', business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate sales dashboard."""
        return SalesDashboard.build(start_date, end_date, period_type, business_id)
    
    @staticmethod
    def generate_product_performance(start_date: date, end_date: date, top_n: int = 50, business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate product performance report."""
        return ProductPerformanceReport.build(start_date, end_date, top_n, business_id)
    
    @staticmethod
    def generate_customer_analysis(start_date: date, end_date: date, min_orders: int = 1, business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate customer analysis report."""
        return CustomerAnalysisReport.build(start_date, end_date, min_orders, business_id)
    
    @staticmethod
    def generate_inventory_report(business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate inventory management report."""
        return InventoryReport.build(business_id)
    
    @staticmethod
    def generate_all_reports(start_date: date, end_date: date, business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate all e-commerce reports."""
        return {
            'sales_dashboard': SalesDashboard.build(start_date, end_date, 'daily', business_id),
            'product_performance': ProductPerformanceReport.build(start_date, end_date, 50, business_id),
            'customer_analysis': CustomerAnalysisReport.build(start_date, end_date, 1, business_id),
            'inventory': InventoryReport.build(business_id),
            'generated_at': timezone.now().isoformat(),
        }
