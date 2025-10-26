from django.utils import timezone
import json
import os
from django.http import HttpRequest
from django.contrib.sites.models import Site
from django.conf import settings
import logging
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

from core.models import *
from business.models import Bussiness, BusinessLocation

class CoreMiddleware(MiddlewareMixin):
    def __init__(self, get_response):
        self.get_response = get_response
        # Class-level flags to track initialization status
        self._business_initialized = False
        self._sites_initialized = False
        self._app_settings_initialized = False
        self._overtime_initialized = False

    def __call__(self, request):
        # Only run initialization logic once per server startup
        if not self._business_initialized:
            self._initialize_business_and_branch()
        
        # Banner initialization moved to campaigns app
        
        if not self._sites_initialized:
            self._initialize_sites(request)
        
        if not self._app_settings_initialized:
            self._initialize_app_settings()
        
        if not self._overtime_initialized:
            self._initialize_overtime_settings()
        
        # Set request data environment variable
        self._set_request_data(request)
        
        if self.get_response:
            response = self.get_response(request)
            return response
        # If no response handler, return a default response
        from django.http import HttpResponse
        return HttpResponse("Middleware error", status=500)

    def _initialize_business_and_branch(self):
        """Initialize business and branch only if they don't exist"""
        try:
            # Check if business already exists
            if Bussiness.objects.exists():
                self._business_initialized = True
                return
            
            # Check if any users exist first
            if not User.objects.exists():
                logger.warning("No users exist yet. Skipping business initialization until users are created.")
                return
            
            # Create default business only if none exists
            default_business = Bussiness.objects.create(
                name='BengoBox ERP', 
                owner=User.objects.first()
            )
            logger.info(f"Created default business: {default_business.name}")
            
            # Create default business location
            default_location = BusinessLocation.objects.create(
                city='Nairobi',
                county='Nairobi',
                state='KE',
                country='KE',
                zip_code='00100',
                postal_code='00100',
                website='codevertexitsolutions.com',
                default=True,
                is_active=True
            )
            logger.info(f"Created default business location: {default_location.city}")
            
            # Create default branch
            business_branch = Branch.objects.create(
                business=default_business,
                location=default_location,
                name="Main Branch",
                is_main_branch=True
            )
            logger.info(f"Created default branch: {business_branch.name}")
            
            self._business_initialized = True
            logger.info("Business initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing business: {str(e)}")
            # Don't mark as initialized if there's an error, so we can try again
            self._business_initialized = False

    # Banner initialization moved to campaigns app

    def _initialize_sites(self, request):
        """Initialize Django sites only if they don't exist"""
        try:
            # Check if sites already exist
            if Site.objects.exists():
                self._sites_initialized = True
                return
            
            # Create backend URL site
            backend_site, created = Site.objects.get_or_create(
                domain=request.scheme + "://" + request.get_host(),
                defaults={'name': "backend_url"}
            )
            if created:
                logger.info(f"Created backend site: {backend_site.domain}")
            
            # Create frontend URL site
            frontend_domain = request.scheme + "://" + str(request.get_host()).replace('8000', '5173' if settings.DEBUG else '8080')
            frontend_site, created = Site.objects.get_or_create(
                domain=frontend_domain,
                defaults={'name': "frontend_url"}
            )
            if created:
                logger.info(f"Created frontend site: {frontend_site.domain}")
            
            self._sites_initialized = True
            logger.info("Sites initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing sites: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._sites_initialized = True

    def _initialize_app_settings(self):
        """Initialize app settings only if they don't exist"""
        try:
            # Check if app settings already exist
            if AppSettings.objects.exists():
                self._app_settings_initialized = True
                return
            
            # Create default app settings
            app_settings, created = AppSettings.objects.get_or_create(name="Default")
            if created:
                logger.info(f"Created default app settings: {app_settings.name}")
            
            self._app_settings_initialized = True
            logger.info("App settings initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing app settings: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._app_settings_initialized = True

    def _initialize_overtime_settings(self):
        """
        Initialize general HR settings (overtime, partial months, rounding)
        Uses new consolidated GeneralHRSettings model
        """
        try:
            from hrm.payroll_settings.models import GeneralHRSettings
            
            # Check if settings already exist
            if GeneralHRSettings.objects.exists():
                self._overtime_initialized = True
                return
            
            # Create default general HR settings (Singleton)
            settings = GeneralHRSettings.load()
            logger.info(f"Created General HR Settings with overtime rates: Normal={settings.overtime_normal_days}x, "
                       f"Weekend={settings.overtime_non_working_days}x, Holidays={settings.overtime_holidays}x")
            
            self._overtime_initialized = True
            logger.info("General HR settings initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing general HR settings: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._overtime_initialized = True

    def _set_request_data(self, request):
        """Set request data environment variable"""
        try:
            request_data = {
                'HTTP_HOST': request.META.get('HTTP_HOST', '127.0.0.1:8000'),
                'HTTP_X_FORWARDED_PROTO': request.META.get('HTTP_X_FORWARDED_PROTO', 'http'),
                'HTTP_REFERER': request.META.get('HTTP_REFERER', ''),
                'REMOTE_ADDR': request.META.get('REMOTE_ADDR', ''),
                'CSRF_COOKIE': request.META.get('CSRF_COOKIE', ''),
                'REQUEST_URL': request.scheme + "://" + request.get_host()
            }
            request_json = json.dumps(request_data)
            os.environ['REQUEST_DATA'] = request_json
        except Exception as e:
            logger.error(f"Error setting request data: {str(e)}")

    def process_request(self, request):
        # Log incoming requests for debugging
        if request.method == 'OPTIONS':
            logger.debug(f"Preflight request: {request.path}")
            # Handle preflight OPTIONS requests
            from django.http import HttpResponse
            response = HttpResponse()
            response['Access-Control-Allow-Origin'] = request.META.get('HTTP_ORIGIN', '*')
            response['Access-Control-Allow-Credentials'] = 'true'
            response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken, X-Branch-ID, X-Business-ID, X-Requested-With, Accept, Origin, DNT, User-Agent, X-Requested-With, If-Modified-Since, Cache-Control, Content-Type, Range'
            response['Access-Control-Max-Age'] = '86400'
            response['Access-Control-Expose-Headers'] = 'Content-Type, X-CSRFToken, X-Branch-ID, X-Business-ID'
            return response
        else:
            logger.debug(f"Request: {request.method} {request.path}")
        
        return None

    def process_response(self, request, response):
        # Ensure CORS headers are always present
        origin = request.META.get('HTTP_ORIGIN')
        if origin:
            # Check if origin is allowed
            allowed_origins = [
                'http://127.0.0.1:5173',
                'http://localhost:5173',
                'http://127.0.0.1:3000',
                'http://localhost:3000',
                'http://127.0.0.1:8080',
                'http://localhost:8080',
                'http://127.0.0.1:4173',
                'http://localhost:4173',
            ]
            
            if origin in allowed_origins:
                response['Access-Control-Allow-Origin'] = origin
                response['Access-Control-Allow-Credentials'] = 'true'
                
                # Handle preflight requests
                if request.method == 'OPTIONS':
                    response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
                    response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-CSRFToken, X-Branch-ID, X-Business-ID, X-Requested-With, Accept, Origin, DNT, User-Agent, X-Requested-With, If-Modified-Since, Cache-Control, Content-Type, Range'
                    response['Access-Control-Max-Age'] = '86400'
                    response['Access-Control-Expose-Headers'] = 'Content-Type, X-CSRFToken, X-Branch-ID, X-Business-ID'
                    # Return early for OPTIONS requests
                    return response
        
        return response