"""
Centralized cache management for all ERP modules
"""
import json
import hashlib
from typing import Any, Optional, Dict, List
from django.core.cache import cache
from django.conf import settings
from django.core.cache.utils import make_template_fragment_key
from django.template.loader import render_to_string
import logging
from functools import wraps
import time

logger = logging.getLogger('ditapi_logger')


class CacheManager:
    """
    Centralized cache manager for all ERP modules
    """
    
    def __init__(self):
        self.default_timeout = getattr(settings, 'CACHE_DEFAULT_TIMEOUT', 300)  # 5 minutes
        self.cache_prefix = getattr(settings, 'CACHE_PREFIX', 'erp')
    
    def _make_key(self, key: str, module: str = None, user_id: int = None) -> str:
        """Generate cache key with prefix and context"""
        parts = [self.cache_prefix]
        
        if module:
            parts.append(module)
        
        if user_id:
            parts.append(f"user_{user_id}")
        
        parts.append(key)
        return ":".join(parts)
    
    def get(self, key: str, module: str = None, user_id: int = None, default: Any = None) -> Any:
        """Get value from cache"""
        cache_key = self._make_key(key, module, user_id)
        try:
            value = cache.get(cache_key, default)
            logger.debug(f"Cache GET: {cache_key} -> {'HIT' if value != default else 'MISS'}")
            return value
        except Exception as e:
            logger.error(f"Cache GET error for {cache_key}: {e}")
            return default
    
    def set(self, key: str, value: Any, timeout: int = None, module: str = None, user_id: int = None) -> bool:
        """Set value in cache"""
        cache_key = self._make_key(key, module, user_id)
        timeout = timeout or self.default_timeout
        
        try:
            result = cache.set(cache_key, value, timeout)
            logger.debug(f"Cache SET: {cache_key} (timeout: {timeout}s)")
            return result
        except Exception as e:
            logger.error(f"Cache SET error for {cache_key}: {e}")
            return False
    
    def delete(self, key: str, module: str = None, user_id: int = None) -> bool:
        """Delete value from cache"""
        cache_key = self._make_key(key, module, user_id)
        try:
            result = cache.delete(cache_key)
            logger.debug(f"Cache DELETE: {cache_key}")
            return result
        except Exception as e:
            logger.error(f"Cache DELETE error for {cache_key}: {e}")
            return False
    
    def get_or_set(self, key: str, callable_func, timeout: int = None, module: str = None, user_id: int = None) -> Any:
        """Get value from cache or set it using callable"""
        cache_key = self._make_key(key, module, user_id)
        timeout = timeout or self.default_timeout
        
        try:
            value = cache.get_or_set(cache_key, callable_func, timeout)
            logger.debug(f"Cache GET_OR_SET: {cache_key}")
            return value
        except Exception as e:
            logger.error(f"Cache GET_OR_SET error for {cache_key}: {e}")
            return callable_func()
    
    def clear_pattern(self, pattern: str, module: str = None) -> int:
        """Clear cache keys matching pattern"""
        try:
            # This is a simplified implementation
            # In production, you might want to use Redis SCAN for better performance
            cache_key_pattern = self._make_key(pattern, module)
            # Implementation depends on cache backend
            logger.info(f"Cache CLEAR_PATTERN: {cache_key_pattern}")
            return 0  # Return number of keys cleared
        except Exception as e:
            logger.error(f"Cache CLEAR_PATTERN error for {pattern}: {e}")
            return 0
    
    def clear_module(self, module: str) -> int:
        """Clear all cache for a specific module"""
        return self.clear_pattern("*", module)
    
    def clear_user(self, user_id: int) -> int:
        """Clear all cache for a specific user"""
        return self.clear_pattern("*", user_id=user_id)
    
    def clear_all(self) -> bool:
        """Clear entire cache"""
        try:
            cache.clear()
            logger.info("Cache CLEAR_ALL: Success")
            return True
        except Exception as e:
            logger.error(f"Cache CLEAR_ALL error: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            # This is a simplified implementation
            # Actual implementation depends on cache backend
            return {
                'backend': str(type(cache).__name__),
                'default_timeout': self.default_timeout,
                'prefix': self.cache_prefix
            }
        except Exception as e:
            logger.error(f"Cache STATS error: {e}")
            return {}


# Global cache manager instance
cache_manager = CacheManager()


def cached(timeout: int = None, module: str = None, user_specific: bool = False):
    """
    Decorator for caching function results
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            key_parts = [func.__name__]
            
            # Add module if specified
            if module:
                key_parts.append(module)
            
            # Add user ID if user-specific
            if user_specific and args and hasattr(args[0], 'user'):
                key_parts.append(f"user_{args[0].user.id}")
            
            # Add arguments hash
            args_hash = hashlib.md5(
                json.dumps([str(arg) for arg in args] + [str(kwargs)], sort_keys=True).encode()
            ).hexdigest()[:8]
            key_parts.append(args_hash)
            
            cache_key = "_".join(key_parts)
            
            # Try to get from cache
            result = cache_manager.get(cache_key, module)
            if result is not None:
                return result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache_manager.set(cache_key, result, timeout, module)
            
            return result
        
        return wrapper
    return decorator


def cache_invalidate(pattern: str, module: str = None):
    """
    Decorator for invalidating cache when function is called
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            cache_manager.clear_pattern(pattern, module)
            return result
        
        return wrapper
    return decorator


class CacheKeyBuilder:
    """
    Helper class for building consistent cache keys
    """
    
    @staticmethod
    def user_data(user_id: int, data_type: str) -> str:
        """Build cache key for user-specific data"""
        return f"user_{user_id}_{data_type}"
    
    @staticmethod
    def module_data(module: str, data_type: str, identifier: str = None) -> str:
        """Build cache key for module-specific data"""
        key = f"{module}_{data_type}"
        if identifier:
            key += f"_{identifier}"
        return key
    
    @staticmethod
    def query_cache(model_name: str, filters: Dict[str, Any]) -> str:
        """Build cache key for database query results"""
        filters_str = "_".join([f"{k}_{v}" for k, v in sorted(filters.items())])
        return f"query_{model_name}_{filters_str}"
    
    @staticmethod
    def template_cache(template_name: str, context_hash: str) -> str:
        """Build cache key for rendered templates"""
        return f"template_{template_name}_{context_hash}"


# Common cache keys for ERP modules
class CacheKeys:
    """Common cache key constants"""
    
    # User-related
    USER_PROFILE = "user_profile"
    USER_PERMISSIONS = "user_permissions"
    USER_PREFERENCES = "user_preferences"
    
    # Module-related
    PAYROLL_FORMULAS = "payroll_formulas"
    EMPLOYEE_DATA = "employee_data"
    DEPARTMENT_LIST = "department_list"
    REGION_LIST = "region_list"
    
    # System-related
    SYSTEM_SETTINGS = "system_settings"
    BUSINESS_CONFIG = "business_config"
    TAX_RATES = "tax_rates"
    
    # Reports
    REPORT_DATA = "report_data"
    DASHBOARD_STATS = "dashboard_stats"
    
    # Tasks
    TASK_STATUS = "task_status"
    BACKGROUND_JOB = "background_job"


def get_cache_key(key_type: str, **kwargs) -> str:
    """
    Get standardized cache key
    """
    builder = CacheKeyBuilder()
    
    if key_type == "user_data":
        return builder.user_data(kwargs['user_id'], kwargs['data_type'])
    elif key_type == "module_data":
        return builder.module_data(kwargs['module'], kwargs['data_type'], kwargs.get('identifier'))
    elif key_type == "query_cache":
        return builder.query_cache(kwargs['model_name'], kwargs['filters'])
    elif key_type == "template_cache":
        return builder.template_cache(kwargs['template_name'], kwargs['context_hash'])
    else:
        return kwargs.get('custom_key', key_type)
