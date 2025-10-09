"""
Centralized caching views for all ERP modules
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from django.conf import settings

from .cache_manager import cache_manager, CacheKeys


class CacheViewSet(viewsets.ViewSet):
    """
    Centralized cache management for all ERP modules
    """
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get cache statistics"""
        try:
            stats = cache_manager.get_stats()
            return Response(stats)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def clear(self, request):
        """Clear cache"""
        try:
            cache_key = request.data.get('key')
            module = request.data.get('module')
            pattern = request.data.get('pattern')
            
            if cache_key:
                # Clear specific key
                result = cache_manager.delete(cache_key, module)
                message = f"Cache key '{cache_key}' {'cleared' if result else 'not found'}"
            elif pattern:
                # Clear pattern
                count = cache_manager.clear_pattern(pattern, module)
                message = f"Cleared {count} cache keys matching pattern '{pattern}'"
            elif module:
                # Clear module cache
                count = cache_manager.clear_module(module)
                message = f"Cleared {count} cache keys for module '{module}'"
            else:
                # Clear all cache
                result = cache_manager.clear_all()
                message = "All cache cleared" if result else "Failed to clear cache"
            
            return Response({'message': message})
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def get(self, request):
        """Get cache value"""
        try:
            cache_key = request.query_params.get('key')
            module = request.query_params.get('module')
            user_id = request.query_params.get('user_id')
            
            if not cache_key:
                return Response(
                    {'error': 'key parameter required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            value = cache_manager.get(cache_key, module, user_id)
            
            return Response({
                'key': cache_key,
                'value': value,
                'found': value is not None
            })
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def set(self, request):
        """Set cache value"""
        try:
            cache_key = request.data.get('key')
            value = request.data.get('value')
            timeout = request.data.get('timeout', 300)
            module = request.data.get('module')
            user_id = request.data.get('user_id')
            
            if not cache_key or value is None:
                return Response(
                    {'error': 'key and value parameters required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            result = cache_manager.set(cache_key, value, timeout, module, user_id)
            
            return Response({
                'key': cache_key,
                'success': result,
                'message': f"Cache key '{cache_key}' {'set' if result else 'failed to set'}"
            })
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def keys(self, request):
        """Get common cache keys"""
        try:
            keys = {
                'user_related': [
                    CacheKeys.USER_PROFILE,
                    CacheKeys.USER_PERMISSIONS,
                    CacheKeys.USER_PREFERENCES
                ],
                'module_related': [
                    CacheKeys.PAYROLL_FORMULAS,
                    CacheKeys.EMPLOYEE_DATA,
                    CacheKeys.DEPARTMENT_LIST,
                    CacheKeys.REGION_LIST
                ],
                'system_related': [
                    CacheKeys.SYSTEM_SETTINGS,
                    CacheKeys.BUSINESS_CONFIG,
                    CacheKeys.TAX_RATES
                ],
                'reports': [
                    CacheKeys.REPORT_DATA,
                    CacheKeys.DASHBOARD_STATS
                ],
                'tasks': [
                    CacheKeys.TASK_STATUS,
                    CacheKeys.BACKGROUND_JOB
                ]
            }
            
            return Response(keys)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
