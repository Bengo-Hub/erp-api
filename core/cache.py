"""
Cache management utilities for the ERP system.
This module provides helper functions for caching frequently accessed data.
"""
from django.core.cache import cache
import hashlib
import json
import logging
from functools import wraps
from django.conf import settings
from datetime import datetime

logger = logging.getLogger('ditapi_logger')

def get_cache_key(prefix, *args, **kwargs):
    """
    Generate a consistent cache key based on arguments.
    
    Args:
        prefix: A string prefix for the cache key
        *args, **kwargs: Arguments to include in the cache key
    
    Returns:
        A string cache key
    """
    # Convert kwargs to a sorted list of tuples to ensure consistent ordering
    kwargs_str = json.dumps(kwargs, sort_keys=True) if kwargs else ""
    
    # Combine args and kwargs into a string
    key_data = f"{prefix}:{':'.join(str(arg) for arg in args)}:{kwargs_str}"
    
    # Hash long keys to keep them within Redis key length limits
    if len(key_data) > 200:
        return f"{prefix}:{hashlib.md5(key_data.encode()).hexdigest()}"
    
    return key_data

def cache_result(timeout=3600, prefix=None, key_func=None):
    """
    Decorator to cache function results.
    
    Args:
        timeout: Cache timeout in seconds (default: 1 hour)
        prefix: Optional prefix for the cache key
        key_func: Optional function to generate a custom cache key
    
    Example:
        @cache_result(timeout=300, prefix="product_details")
        def get_product_details(product_id):
            # Expensive database query...
            return product_data
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                func_prefix = prefix or f"{func.__module__}.{func.__name__}"
                cache_key = get_cache_key(func_prefix, *args, **kwargs)
            
            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for key: {cache_key}")
                try:
                    stats = cache.get('cache_stats', {
                        'hit_rate': 0,
                        'miss_rate': 0,
                        'total_requests': 0,
                        'hits': 0,
                        'misses': 0,
                        'updated_at': None,
                    })
                    stats['total_requests'] += 1
                    stats['hits'] += 1
                    total = stats['total_requests'] or 1
                    stats['hit_rate'] = round((stats['hits'] / total) * 100, 2)
                    stats['miss_rate'] = round((stats['misses'] / total) * 100, 2)
                    stats['updated_at'] = datetime.utcnow().isoformat()
                    cache.set('cache_stats', stats, timeout=getattr(settings, 'CACHE_STATS_TTL', 3600))
                except Exception:
                    pass
                return cached_result
            
            # If not in cache, call the function
            logger.debug(f"Cache miss for key: {cache_key}")
            result = func(*args, **kwargs)
            
            # Cache the result
            cache.set(cache_key, result, timeout=timeout)
            try:
                stats = cache.get('cache_stats', {
                    'hit_rate': 0,
                    'miss_rate': 0,
                    'total_requests': 0,
                    'hits': 0,
                    'misses': 0,
                    'updated_at': None,
                })
                stats['total_requests'] += 1
                stats['misses'] += 1
                total = stats['total_requests'] or 1
                stats['hit_rate'] = round((stats['hits'] / total) * 100, 2)
                stats['miss_rate'] = round((stats['misses'] / total) * 100, 2)
                stats['updated_at'] = datetime.utcnow().isoformat()
                cache.set('cache_stats', stats, timeout=getattr(settings, 'CACHE_STATS_TTL', 3600))
            except Exception:
                pass
            return result
        
        # Add a method to clear this function's cache
        def clear_cache(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                func_prefix = prefix or f"{func.__module__}.{func.__name__}"
                cache_key = get_cache_key(func_prefix, *args, **kwargs)
            cache.delete(cache_key)
            logger.debug(f"Cleared cache for key: {cache_key}")
        
        wrapper.clear_cache = clear_cache
        return wrapper
    
    return decorator

def invalidate_model_cache(model_instance):
    """
    Invalidate all cache keys related to a specific model instance.
    
    Args:
        model_instance: The model instance that was updated
    """
    model_name = model_instance.__class__.__name__.lower()
    cache_key_pattern = f"{model_name}_*_{model_instance.pk}"
    
    # In a real implementation, you would use Redis's SCAN command
    # For now, we'll log that this should happen
    logger.info(f"Invalidating cache for {model_name} with ID {model_instance.pk}")
    
    # For specific known cache keys, delete them directly
    cache.delete(f"{model_name}_details_{model_instance.pk}")
    cache.delete(f"{model_name}_list")

def bulk_invalidate_cache(patterns):
    """
    Invalidate multiple cache patterns at once.
    
    Args:
        patterns: List of cache key patterns to invalidate
    """
    for pattern in patterns:
        logger.info(f"Bulk invalidating cache pattern: {pattern}")
        # In a production implementation, you would use Redis's SCAN and DEL
        # Since Django's cache framework doesn't support wildcard deletions directly,
        # you might need a Redis client for this functionality

class QuerysetCacheMixin:
    """
    Mixin to add caching capabilities to Django QuerySets.
    """
    
    def cached(self, timeout=3600, cache_key=None):
        """
        Return a cached version of the queryset result.
        
        Args:
            timeout: Cache timeout in seconds (default: 1 hour)
            cache_key: Optional custom cache key
        
        Returns:
            Queryset results, either from cache or database
        """
        if not cache_key:
            # Generate a key based on the queryset query
            query_str = str(self.query)
            model_name = self.model.__name__.lower()
            cache_key = f"{model_name}_queryset_{hashlib.md5(query_str.encode()).hexdigest()}"
        
        result = cache.get(cache_key)
        if result is not None:
            logger.debug(f"Queryset cache hit for key: {cache_key}")
            return result
        
        logger.debug(f"Queryset cache miss for key: {cache_key}")
        result = list(self.all())
        cache.set(cache_key, result, timeout=timeout)
        return result
