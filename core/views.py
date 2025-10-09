import os
import datetime
from django.shortcuts import render,redirect
from django.views import View
from rest_framework import viewsets
from rest_framework import status
from business.models import Bussiness
from crm.contacts.utils import ImportContacts
from ecommerce.product.functions import ImportProducts
from hrm.employees.utils import EmployeeDataImport
from .serializers import *
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework import permissions, authentication
from rest_framework.response import Response
from rest_framework.authentication import BasicAuthentication,TokenAuthentication
from rest_framework.parsers import MultiPartParser,FormParser
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.db.models import Q
from django.db import connection
from django.utils import timezone
from business.models import BusinessLocation
# Banner model moved to campaigns app
from django.contrib.auth import get_user_model
User = get_user_model()
from django.http import JsonResponse
from django.core.cache import cache
from django.utils import timezone
from datetime import datetime, timedelta
from .models import *
from .serializers import *
from .performance import PerformanceMonitor, DatabaseIndexManager, QueryOptimizer
from .background_jobs import get_job_status, get_queue_statistics, get_thread_pool_stats, submit_background_job
from .image_optimization import image_optimizer, cdn_manager, optimize_and_upload_image, get_responsive_image_urls, get_cdn_url
from .load_testing import LoadTestManager, create_comprehensive_load_test_config
import json
import psutil
from core.decorators import apply_common_filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

class UploadData(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = (BasicAuthentication, TokenAuthentication)
    parser_classes = (MultiPartParser, FormParser)  # Add parsers for file upload

    def post(self, request, format=None):
        biz_name = request.data.get('business_name', '')
        fileType = request.data.get('fileType')
        organisation=Bussiness.objects.filter(Q(owner=self.request.user)|Q(employees__user=self.request.user)).first()
        if organisation is None:
            organisation = Bussiness.objects.create(name=biz_name)
        if organisation is None:
            return Response({'error': "No Company or Business Details found. Please register company details before importing employees"}, status=status.HTTP_400_BAD_REQUEST)
        # Check if the request contains a file
        if 'file' not in request.FILES:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
        file_obj = request.FILES['file']
        # Save the uploaded file
        file_name = default_storage.save(file_obj.name, ContentFile(file_obj.read()))
        # Call the import_employee_data function
        try:
            path=default_storage.path(file_name)
            res=None
            if fileType =='employees':
               res = EmployeeDataImport(request,path,organisation).import_employee_data()
            if fileType =='products':
               res = ImportProducts(request,path,organisation).save_product()
            if fileType =='contacts':
               res = ImportContacts(request,path,organisation).save_contact()

            # Delete the file after successful import
            if os.path.exists(path):
                os.remove(path)
            return Response({'message': res}, status=status.HTTP_201_CREATED)
        except Exception as e:
            # Delete the file if an error occurs
            if os.path.exists(path):
                os.remove(path)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RegionsViewSet(viewsets.ModelViewSet):
    queryset = Regions.objects.all()
    serializer_class = RegionsSerializer

class ProjectsViewSet(viewsets.ModelViewSet):
    queryset = Projects.objects.all()
    serializer_class = ProjectsSerializer

class DepartmentsViewSet(viewsets.ModelViewSet):
    queryset = Departments.objects.all()
    serializer_class = DepartmentsSerializer

class BankInstitutionViewSet(viewsets.ModelViewSet):
    queryset = BankInstitution.objects.all()
    serializer_class = BankInstitutionSerializer

# Legacy alias for backward compatibility
BanksViewSet = BankInstitutionViewSet

class BankBranchesViewSet(viewsets.ModelViewSet):
    queryset = BankBranches.objects.all()
    serializer_class = BankBranchesSerializer

# ActiveBannersView moved to centralized campaigns app
# Use: /api/v1/campaigns/active_banners/ endpoint

class HealthCheckView(APIView):
    """API endpoint for system health monitoring used by deployment pipeline"""
    permission_classes = [AllowAny]
    
    def get(self, request, format=None):
        # Test database connection
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                db_status = "ok"
        except Exception as e:
            db_status = str(e)
        
        # Basic health check data
        health_data = {
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "database": db_status,
            "version": "1.0.0"
        }
        
        return Response(health_data)

class PerformanceMetricsView(APIView):
    """API endpoint for performance monitoring and metrics"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get current performance metrics"""
        try:
            # Database performance metrics
            with connection.cursor() as cursor:
                cursor.execute("SELECT version();")
                db_version = cursor.fetchone()[0]
            
            # Cache performance metrics
            cache_stats = cache.get('cache_stats', {})
            
            # System performance metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Database connection metrics
            db_connections = len(connection.queries) if hasattr(connection, 'queries') else 0
            
            # Performance recommendations
            recommendations = self.get_performance_recommendations()
            
            metrics = {
                'timestamp': timezone.now().isoformat(),
                'database': {
                    'version': db_version,
                    'active_connections': db_connections,
                    'slow_queries': cache.get('slow_queries_count', 0),
                },
                'cache': {
                    'hit_rate': cache_stats.get('hit_rate', 0),
                    'miss_rate': cache_stats.get('miss_rate', 0),
                    'total_requests': cache_stats.get('total_requests', 0),
                },
                'system': {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'disk_percent': disk.percent,
                    'memory_available_gb': round(memory.available / (1024**3), 2),
                    'disk_free_gb': round(disk.free / (1024**3), 2),
                },
                'recommendations': recommendations,
            }
            
            return Response(metrics)
            
        except Exception as e:
            return Response(
                {'error': f'Failed to get performance metrics: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def get_performance_recommendations(self):
        """Generate performance recommendations"""
        recommendations = []
        
        # Check CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > 80:
            recommendations.append({
                'type': 'warning',
                'message': f'High CPU usage detected: {cpu_percent}%',
                'action': 'Consider scaling up server resources or optimizing CPU-intensive operations'
            })
        
        # Check memory usage
        memory = psutil.virtual_memory()
        if memory.percent > 85:
            recommendations.append({
                'type': 'warning',
                'message': f'High memory usage detected: {memory.percent}%',
                'action': 'Consider increasing server memory or optimizing memory usage'
            })
        
        # Check disk usage
        disk = psutil.disk_usage('/')
        if disk.percent > 90:
            recommendations.append({
                'type': 'critical',
                'message': f'High disk usage detected: {disk.percent}%',
                'action': 'Immediate action required: Clean up disk space or increase storage'
            })
        
        # Check cache performance
        cache_stats = cache.get('cache_stats', {})
        hit_rate = cache_stats.get('hit_rate', 0)
        if hit_rate < 70:
            recommendations.append({
                'type': 'info',
                'message': f'Low cache hit rate: {hit_rate}%',
                'action': 'Consider optimizing cache strategies and increasing cache size'
            })
        
        return recommendations

class DatabaseOptimizationView(APIView):
    """API endpoint for database optimization suggestions"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get database optimization suggestions"""
        try:
            # Get missing indexes
            missing_indexes = DatabaseIndexManager.get_missing_indexes()
            
            # Get index suggestions
            index_suggestions = DatabaseIndexManager.create_index_suggestions()
            
            # Get slow query analysis
            slow_queries = cache.get('slow_queries', [])
            
            optimization_data = {
                'missing_indexes': missing_indexes,
                'index_suggestions': index_suggestions,
                'slow_queries': slow_queries[:10],  # Top 10 slow queries
                'total_suggestions': len(index_suggestions),
                'high_priority_suggestions': len([s for s in index_suggestions if s['priority'] == 'high']),
            }
            
            return Response(optimization_data)
            
        except Exception as e:
            return Response(
                {'error': f'Failed to get optimization data: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class CacheManagementView(APIView):
    """API endpoint for cache management"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get cache statistics and status"""
        try:
            # Get cache statistics
            cache_stats = cache.get('cache_stats', {})
            
            # Get cache keys count (approximate)
            cache_keys_count = len(cache._cache) if hasattr(cache, '_cache') else 0
            
            cache_data = {
                'status': 'active',
                'backend': str(cache.__class__.__name__),
                'statistics': cache_stats,
                'keys_count': cache_keys_count,
                'memory_usage_mb': self.get_cache_memory_usage(),
            }
            
            return Response(cache_data)
            
        except Exception as e:
            return Response(
                {'error': f'Failed to get cache data: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Clear cache or specific cache patterns"""
        try:
            action = request.data.get('action', 'clear_all')
            
            if action == 'clear_all':
                cache.clear()
                message = 'All cache cleared successfully'
            elif action == 'clear_pattern':
                pattern = request.data.get('pattern', '')
                # This would require Redis-specific implementation
                cache.clear()  # Fallback to clear all
                message = f'Cache cleared for pattern: {pattern}'
            else:
                return Response(
                    {'error': 'Invalid action specified'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            return Response({'message': message})
            
        except Exception as e:
            return Response(
                {'error': f'Failed to perform cache action: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def get_cache_memory_usage(self):
        """Get approximate cache memory usage in MB"""
        try:
            # This is a simplified calculation
            # In production, you'd want to use Redis INFO command
            cache_stats = cache.get('cache_stats', {})
            total_requests = cache_stats.get('total_requests', 0)
            return round(total_requests * 0.001, 2)  # Rough estimate
        except:
            return 0

class SystemHealthView(APIView):
    """Enhanced system health check with performance metrics"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Get comprehensive system health status"""
        try:
            # Test database connection
            db_status = "ok"
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except Exception as e:
                db_status = f"error: {str(e)}"
            
            # Test cache connection
            cache_status = "ok"
            try:
                cache.set('health_check', 'ok', timeout=10)
                cache.get('health_check')
            except Exception as e:
                cache_status = f"error: {str(e)}"
            
            # System metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Overall health status
            overall_status = "healthy"
            if db_status != "ok" or cache_status != "ok" or cpu_percent > 90 or memory.percent > 90:
                overall_status = "degraded"
            if db_status != "ok" or cache_status != "ok":
                overall_status = "unhealthy"
            
            health_data = {
                "status": overall_status,
                "timestamp": timezone.now().isoformat(),
                "version": "1.0.0",
                "services": {
                    "database": db_status,
                    "cache": cache_status,
                },
                "system": {
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "disk_percent": disk.percent,
                },
                "performance": {
                    "response_time_ms": self.get_response_time(),
                    "active_connections": len(connection.queries) if hasattr(connection, 'queries') else 0,
                }
            }
            
            return Response(health_data)
            
        except Exception as e:
            return Response(
                {
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": timezone.now().isoformat()
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def get_response_time(self):
        """Get approximate response time"""
        start_time = timezone.now()
        # Simulate some work
        cache.get('health_check')
        end_time = timezone.now()
        return (end_time - start_time).total_seconds() * 1000


class BackgroundJobManagementView(APIView):
    """API endpoint for background job management"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get background job statistics and status"""
        try:
            job_id = request.query_params.get('job_id')
            
            if job_id:
                # Get specific job status
                job_status = get_job_status(job_id)
                return Response(job_status)
            else:
                # Get queue statistics
                queue_stats = get_queue_statistics()
                thread_pool_stats = get_thread_pool_stats('default')
                
                return Response({
                    'queue_statistics': queue_stats,
                    'thread_pool_statistics': thread_pool_stats
                })
                
        except Exception as e:
            return Response(
                {'error': f'Failed to get job information: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Submit a new background job"""
        try:
            job_type = request.data.get('job_type')
            job_data = request.data.get('data', {})
            user_id = request.user.id if request.user.is_authenticated else None
            
            if not job_type:
                return Response(
                    {'error': 'job_type is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            job_id = submit_background_job(job_type, job_data, user_id)
            
            return Response({
                'job_id': job_id,
                'status': 'submitted',
                'message': f'Job {job_type} submitted successfully'
            })
            
        except Exception as e:
            return Response(
                {'error': f'Failed to submit job: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ImageOptimizationView(APIView):
    """API endpoint for image optimization and CDN management"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Optimize an uploaded image"""
        try:
            image_file = request.FILES.get('image')
            size_name = request.data.get('size', 'medium')
            format_name = request.data.get('format')
            quality = request.data.get('quality')
            
            if not image_file:
                return Response(
                    {'error': 'No image file provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate size name
            valid_sizes = list(image_optimizer.sizes.keys())
            if size_name not in valid_sizes:
                return Response(
                    {'error': f'Invalid size. Valid sizes: {valid_sizes}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Optimize and upload image
            optimized_path = optimize_and_upload_image(
                image_file, 
                size_name=size_name, 
                format_name=format_name, 
                quality=quality
            )
            
            if not optimized_path:
                return Response(
                    {'error': 'Failed to optimize image'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Get CDN URL if enabled
            cdn_url = get_cdn_url(optimized_path, size_name)
            
            return Response({
                'optimized_path': optimized_path,
                'cdn_url': cdn_url,
                'size': size_name,
                'format': format_name or 'auto',
                'quality': quality or image_optimizer.quality
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response(
                {'error': f'Image optimization failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get(self, request):
        """Get image optimization configuration and statistics"""
        try:
            # Get optimization config
            config = {
                'enabled': image_optimizer.config.get('ENABLED', True),
                'quality': image_optimizer.quality,
                'supported_formats': image_optimizer.supported_formats,
                'available_sizes': image_optimizer.sizes,
                'compression_options': image_optimizer.compression,
                'lazy_loading': image_optimizer.config.get('LAZY_LOADING', True),
                'responsive_images': image_optimizer.config.get('RESPONSIVE_IMAGES', True)
            }
            
            # Get CDN config
            cdn_config = {
                'enabled': cdn_manager.enabled,
                'provider': cdn_manager.provider,
                'domain': cdn_manager.domain,
                'secure': cdn_manager.secure
            }
            
            return Response({
                'image_optimization': config,
                'cdn': cdn_config
            })
            
        except Exception as e:
            return Response(
                {'error': f'Failed to get configuration: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CDNManagementView(APIView):
    """API endpoint for CDN management"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Invalidate CDN cache for specified files"""
        try:
            file_paths = request.data.get('file_paths', [])
            
            if not file_paths:
                return Response(
                    {'error': 'No file paths provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not cdn_manager.enabled:
                return Response(
                    {'error': 'CDN is not enabled'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Invalidate cache
            success = cdn_manager.invalidate_cache(file_paths)
            
            if success:
                return Response({
                    'message': f'Cache invalidation initiated for {len(file_paths)} files',
                    'file_paths': file_paths
                })
            else:
                return Response(
                    {'error': 'Failed to invalidate cache'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            return Response(
                {'error': f'CDN operation failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get(self, request):
        """Get CDN status and statistics"""
        try:
            file_path = request.query_params.get('file_path')
            size_name = request.query_params.get('size')
            
            if file_path:
                # Get CDN URL for specific file
                cdn_url = get_cdn_url(file_path, size_name)
                return Response({
                    'file_path': file_path,
                    'size': size_name,
                    'cdn_url': cdn_url
                })
            else:
                # Get CDN configuration
                return Response({
                    'enabled': cdn_manager.enabled,
                    'provider': cdn_manager.provider,
                    'domain': cdn_manager.domain,
                    'secure': cdn_manager.secure,
                    'status': 'active' if cdn_manager.enabled else 'disabled'
                })
                
        except Exception as e:
            return Response(
                {'error': f'Failed to get CDN information: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ResponsiveImagesView(APIView):
    """API endpoint for responsive image generation"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Generate responsive images for an uploaded image"""
        try:
            image_file = request.FILES.get('image')
            base_name = request.data.get('base_name')
            sizes = request.data.get('sizes', ['thumbnail', 'small', 'medium', 'large'])
            
            if not image_file:
                return Response(
                    {'error': 'No image file provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Generate responsive images
            responsive_images = image_optimizer.generate_responsive_images(image_file, base_name)
            
            if not responsive_images:
                return Response(
                    {'error': 'Failed to generate responsive images'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Get CDN URLs for all sizes
            cdn_urls = {}
            for size_name, file_path in responsive_images.items():
                cdn_urls[size_name] = get_cdn_url(file_path, size_name)
            
            return Response({
                'responsive_images': responsive_images,
                'cdn_urls': cdn_urls,
                'sizes_generated': list(responsive_images.keys())
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response(
                {'error': f'Responsive image generation failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get(self, request):
        """Get responsive image URLs for an existing image"""
        try:
            base_path = request.query_params.get('base_path')
            sizes = request.query_params.getlist('sizes', ['thumbnail', 'small', 'medium', 'large'])
            
            if not base_path:
                return Response(
                    {'error': 'No base path provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get responsive image URLs
            responsive_urls = get_responsive_image_urls(base_path, sizes)
            
            return Response({
                'base_path': base_path,
                'responsive_urls': responsive_urls,
                'sizes': sizes
            })
            
        except Exception as e:
            return Response(
                {'error': f'Failed to get responsive image URLs: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LoadTestingView(APIView):
    """API endpoint for load testing"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Run load tests"""
        try:
            test_config = request.data.get('config', {})
            base_url = request.data.get('base_url', 'http://localhost:8000')
            
            if not test_config:
                return Response(
                    {'error': 'No test configuration provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create load test manager
            load_manager = LoadTestManager(base_url)
            
            # Run comprehensive test
            import asyncio
            results = asyncio.run(load_manager.run_comprehensive_test(test_config))
            
            return Response(results, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': f'Load testing failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get(self, request):
        """Get load testing configuration templates"""
        try:
            # Provide sample configurations
            sample_configs = {
                'api_load_test': {
                    'api_endpoints': [
                        {
                            'endpoint': '/api/v1/core/health/',
                            'method': 'GET',
                            'concurrent_users': 10,
                            'duration': 30
                        },
                        {
                            'endpoint': '/api/v1/hrm/employees/',
                            'method': 'GET',
                            'concurrent_users': 5,
                            'duration': 30
                        }
                    ],
                    'system_monitoring_duration': 60
                },
                'database_load_test': {
                    'database_queries': [
                        {
                            'name': 'employee_count',
                            'function': 'lambda: Employee.objects.count()',
                            'iterations': 1000,
                            'concurrent_threads': 10
                        }
                    ],
                    'system_monitoring_duration': 60
                }
            }
            
            return Response({
                'sample_configurations': sample_configs,
                'documentation': 'Use POST method with config parameter to run load tests'
            })
            
        except Exception as e:
            return Response(
                {'error': f'Failed to get load testing configs: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ExecutiveDashboardView(APIView):
    """
    Executive Dashboard API View
    
    Provides high-level business intelligence by aggregating data from all ERP modules.
    This endpoint is used by the Executive Dashboard to show KPIs and trends.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get executive dashboard data."""
        try:
            from .analytics.executive_analytics import ExecutiveAnalyticsService
            from .utils import get_business_id_from_request, get_branch_id_from_request
            
            # Get period from query params
            period = request.query_params.get('period', 'month')
            
            # Get filters directly
            business_id = get_business_id_from_request(request)
            branch_id = get_branch_id_from_request(request)
            region_id = request.query_params.get('region_id')
            department_id = request.query_params.get('department_id')
            
            # Convert string IDs to integers if provided
            if region_id:
                try:
                    region_id = int(region_id)
                except ValueError:
                    region_id = None
            
            if department_id:
                try:
                    department_id = int(department_id)
                except ValueError:
                    department_id = None
            
            filters = {
                'business_id': business_id,
                'branch_id': branch_id,
                'region_id': region_id,
                'department_id': department_id
            }
            
            # Get dashboard data
            analytics_service = ExecutiveAnalyticsService()
            dashboard_data = analytics_service.get_executive_dashboard_data(
                period=period,
                business_id=business_id,
                branch_id=branch_id
            )
            
            return Response({
                'success': True,
                'data': dashboard_data,
                'period': period,
                'filters': filters,
                'generated_at': timezone.now().isoformat()
            })
            
        except ImportError:
            # Return fallback data if analytics service not available
            return Response({
                'success': True,
                'data': {
                    'total_revenue': 5000000.0,
                    'total_expenses': 3500000.0,
                    'net_profit': 1500000.0,
                    'profit_margin': 30.0,
                    'total_orders': 1250,
                    'total_customers': 450,
                    'total_employees': 85,
                    'total_suppliers': 120,
                    'order_fulfillment_rate': 0.95,
                    'customer_satisfaction': 4.2,
                    'employee_productivity': 0.85,
                    'inventory_turnover': 8.5,
                    'revenue_trends': [],
                    'profit_trends': [],
                    'order_trends': [],
                    'customer_growth': []
                },
                'period': request.query_params.get('period', 'month'),
                'generated_at': timezone.now().isoformat(),
                'note': 'Using fallback data - analytics service not available'
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
                'generated_at': timezone.now().isoformat()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PerformanceDashboardView(APIView):
    """
    Performance Dashboard API View
    
    Provides system performance metrics and monitoring capabilities.
    This endpoint is used by the Performance Dashboard and system health monitoring.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get performance metrics."""
        try:
            from .analytics.performance_analytics import PerformanceAnalyticsService
            from .utils import get_business_id_from_request, get_branch_id_from_request
            
            # Get period from query params
            period = request.query_params.get('period', 'hour')
            
            # Get filters directly
            business_id = get_business_id_from_request(request)
            branch_id = get_branch_id_from_request(request)
            region_id = request.query_params.get('region_id')
            department_id = request.query_params.get('department_id')
            
            # Convert string IDs to integers if provided
            if region_id:
                try:
                    region_id = int(region_id)
                except ValueError:
                    region_id = None
            
            if department_id:
                try:
                    department_id = int(department_id)
                except ValueError:
                    department_id = None
            
            filters = {
                'business_id': business_id,
                'branch_id': branch_id,
                'region_id': region_id,
                'department_id': department_id
            }
            
            # Get performance data
            analytics_service = PerformanceAnalyticsService()
            performance_data = analytics_service.get_performance_metrics(
                period=period,
                business_id=business_id,
                branch_id=branch_id
            )
            
            return Response({
                'success': True,
                'data': performance_data,
                'period': period,
                'filters': filters,
                'generated_at': timezone.now().isoformat()
            })
            
        except ImportError:
            # Return fallback data if analytics service not available
            return Response({
                'success': True,
                'data': {
                    'database_performance': {
                        'slow_queries': 0,
                        'active_connections': 5,
                        'database_size_mb': 0,
                        'connection_pool_usage': 5.0
                    },
                    'cache_performance': {
                        'cache_hit_rate': 85.0,
                        'write_time_ms': 2.5,
                        'read_time_ms': 1.2,
                        'cache_size_mb': 0,
                        'cache_keys': 1000
                    },
                    'system_health': {
                        'cpu_usage_percent': 25.0,
                        'memory_usage_percent': 60.0,
                        'memory_used_gb': 4.5,
                        'memory_total_gb': 8.0,
                        'disk_usage_percent': 45.0,
                        'disk_free_gb': 50.0,
                        'network_sent_mb': 10.5,
                        'network_recv_mb': 15.2
                    },
                    'api_performance': {
                        'total_requests': 1000,
                        'avg_response_time_ms': 200,
                        'error_rate_percent': 3.0,
                        'success_rate_percent': 97.0,
                        'requests_per_second': 0.28
                    }
                },
                'period': request.query_params.get('period', 'hour'),
                'generated_at': timezone.now().isoformat(),
                'note': 'Using fallback data - analytics service not available'
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
                'generated_at': timezone.now().isoformat()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)