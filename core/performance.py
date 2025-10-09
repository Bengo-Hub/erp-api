"""
Performance optimization utilities for Bengo ERP.
Includes database indexing, query optimization, and performance monitoring.
"""

import logging
from django.db import connection, models
from django.db.models import Index
from django.core.cache import cache
from django.conf import settings
from functools import wraps
import time
import json
from decimal import Decimal

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """Monitor and log performance metrics"""
    
    def __init__(self):
        self.metrics = {}
    
    def start_timer(self, operation_name):
        """Start timing an operation"""
        self.metrics[operation_name] = {
            'start_time': time.time(),
            'queries_before': len(connection.queries)
        }
    
    def end_timer(self, operation_name):
        """End timing an operation and log metrics"""
        if operation_name in self.metrics:
            end_time = time.time()
            duration = end_time - self.metrics[operation_name]['start_time']
            queries_after = len(connection.queries)
            queries_executed = queries_after - self.metrics[operation_name]['queries_before']
            
            logger.info(f"Performance: {operation_name} took {duration:.3f}s with {queries_executed} queries")
            try:
                from core.models import QueryPerformanceMetric
                QueryPerformanceMetric.objects.create(
                    operation=operation_name,
                    duration_ms=Decimal(f"{duration * 1000:.3f}"),
                    query_count=queries_executed,
                    extra=None,
                )
            except Exception:
                # Avoid breaking runtime due to metric write errors
                pass
            
            # Store in cache for monitoring
            cache_key = f"perf_metrics_{operation_name}"
            cache.set(cache_key, {
                'duration': duration,
                'queries': queries_executed,
                'timestamp': end_time
            }, timeout=3600)
            
            return duration, queries_executed
        return 0, 0

def performance_monitor(operation_name):
    """Decorator to monitor function performance"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            monitor = PerformanceMonitor()
            monitor.start_timer(operation_name)
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                monitor.end_timer(operation_name)
        return wrapper
    return decorator

class DatabaseIndexManager:
    """Manage database indexes for performance optimization"""
    
    @staticmethod
    def get_missing_indexes():
        """Analyze database and return missing indexes"""
        with connection.cursor() as cursor:
            # PostgreSQL specific query to find missing indexes
            cursor.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    attname,
                    n_distinct,
                    correlation
                FROM pg_stats 
                WHERE schemaname = 'public' 
                AND n_distinct > 100 
                AND correlation < 0.8
                ORDER BY n_distinct DESC;
            """)
            return cursor.fetchall()
    
    @staticmethod
    def create_index_suggestions():
        """Generate index creation suggestions based on query patterns"""
        suggestions = []
        
        # Common query patterns that benefit from indexes
        common_patterns = [
            # User queries
            ('authmanagement_customuser', ['email', 'username']),
            ('authmanagement_customuser', ['is_active', 'date_joined']),
            
            # Business queries
            ('business_businesslocation', ['business_id', 'is_active']),
            ('business_businesslocation', ['location_name']),
            
            # Employee queries
            ('hrm_employees_employee', ['employee_id', 'status']),
            ('hrm_employees_employee', ['department_id', 'status']),
            ('hrm_employees_employee', ['hire_date', 'status']),
            
            # Product queries
            ('products', ['sku', 'status']),
            ('products', ['category_id', 'status']),
            ('products', ['brand_id', 'status']),
            
            # Order queries
            ('ecommerce_order_order', ['customer_id', 'status']),
            ('ecommerce_order_order', ['created_at', 'status']),
            ('ecommerce_order_order', ['payment_status', 'status']),
            
            # Inventory queries
            ('ecommerce_stockinventory_stockinventory', ['product_id', 'branch_id']),
            ('ecommerce_stockinventory_stockinventory', ['stock_level', 'branch_id']),
            
            # Financial queries
            ('finance_accounts_transaction', ['account_id', 'transaction_date']),
            ('finance_accounts_transaction', ['transaction_type', 'transaction_date']),
            
            # CRM queries
            ('crm_contacts_contact', ['user_id', 'is_deleted']),
            ('crm_leads_lead', ['status', 'created_at']),
            ('crm_pipeline_deal', ['stage_id', 'close_date']),
        ]
        
        for table, fields in common_patterns:
            suggestions.append({
                'table': table,
                'fields': fields,
                'index_name': f'idx_{table}_{"_".join(fields)}',
                'priority': 'high' if 'status' in fields else 'medium'
            })
        
        return suggestions

class QueryOptimizer:
    """Optimize database queries for better performance"""
    
    @staticmethod
    def optimize_queryset(queryset, select_related=None, prefetch_related=None):
        """Apply common query optimizations"""
        if select_related:
            queryset = queryset.select_related(*select_related)
        if prefetch_related:
            queryset = queryset.prefetch_related(*prefetch_related)
        return queryset
    
    @staticmethod
    def add_pagination(queryset, page_size=50, max_page_size=1000):
        """Add pagination to prevent large result sets"""
        if page_size > max_page_size:
            page_size = max_page_size
        return queryset[:page_size]
    
    @staticmethod
    def cache_queryset(queryset, cache_key, timeout=3600):
        """Cache queryset results"""
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        result = list(queryset)
        cache.set(cache_key, result, timeout=timeout)
        return result

class CacheManager:
    """Manage application caching for performance"""
    
    @staticmethod
    def get_cache_key(prefix, *args, **kwargs):
        """Generate consistent cache keys"""
        key_parts = [prefix]
        key_parts.extend([str(arg) for arg in args])
        key_parts.extend([f"{k}:{v}" for k, v in sorted(kwargs.items())])
        return "_".join(key_parts)
    
    @staticmethod
    def invalidate_pattern(pattern):
        """Invalidate cache entries matching a pattern"""
        # This would require Redis-specific implementation
        # For now, we'll use a simple approach
        cache.clear()
    
    @staticmethod
    def cache_function_result(func, timeout=3600):
        """Decorator to cache function results"""
        def decorator(*args, **kwargs):
            cache_key = CacheManager.get_cache_key(
                func.__name__, 
                *args, 
                **kwargs
            )
            
            result = cache.get(cache_key)
            if result is not None:
                return result
            
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout=timeout)
            return result
        
        return decorator

class PerformanceMiddleware:
    """Middleware to monitor request performance"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        start_time = time.time()
        queries_before = len(connection.queries)
        
        response = self.get_response(request)
        
        end_time = time.time()
        duration = end_time - start_time
        queries_after = len(connection.queries)
        queries_executed = queries_after - queries_before
        
        # Log slow requests
        if duration > 1.0:  # Log requests taking more than 1 second
            logger.warning(
                f"Slow request: {request.path} took {duration:.3f}s "
                f"with {queries_executed} queries"
            )
        
        # Add performance headers
        response['X-Response-Time'] = f"{duration:.3f}s"
        response['X-Query-Count'] = str(queries_executed)
        try:
            from core.models import ApiRequestMetric
            ApiRequestMetric.objects.create(
                method=request.method,
                path=request.path[:512],
                status_code=getattr(response, 'status_code', 0) or 0,
                duration_ms=Decimal(f"{duration * 1000:.3f}"),
                query_count=max(0, queries_executed),
                user_id=getattr(getattr(request, 'user', None), 'id', None),
            )
        except Exception:
            # Avoid breaking requests on metric failures
            pass
        
        return response

# Performance monitoring decorators
def monitor_performance(operation_name):
    """Decorator to monitor function performance"""
    return performance_monitor(operation_name)

def cache_result(timeout=3600):
    """Decorator to cache function results"""
    def decorator(func):
        return CacheManager.cache_function_result(func, timeout=timeout)
    return decorator

# Utility functions for common performance optimizations
def optimize_list_queryset(queryset, page_size=50):
    """Optimize queryset for list views"""
    return QueryOptimizer.optimize_queryset(queryset).select_related(
        'created_by', 'updated_by'
    )[:page_size]

def optimize_detail_queryset(queryset):
    """Optimize queryset for detail views"""
    return QueryOptimizer.optimize_queryset(
        queryset,
        select_related=['created_by', 'updated_by'],
        prefetch_related=['related_objects']
    )

def get_cached_or_none(cache_key):
    """Get cached value or return None"""
    return cache.get(cache_key)

def set_cache_with_timeout(cache_key, value, timeout=3600):
    """Set cache value with timeout"""
    cache.set(cache_key, value, timeout=timeout)
