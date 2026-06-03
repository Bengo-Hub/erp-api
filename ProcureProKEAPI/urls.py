"""
URL configuration for ProcureProKEAPI project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.http import JsonResponse
from apscheduler.schedulers.background import BackgroundScheduler
from hrm.employees.management.commands.tasks import check_expiring_contracts
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

# Prometheus metrics
from django_prometheus.exports import ExportToDjangoView

def api_root(request):
    """Root API endpoint showing available endpoints"""
    return JsonResponse({
        'message': 'Welcome to ProcureProKE ERP API',
        'version': '1.0.0',
        'endpoints': {
            'docs': '/api/docs/',
            'schema': '/api/schema/',
            'admin': '/admin/',
            'health': '/api/v1/core/health/',
            'api_v1': '/api/v1/',
        },
        'documentation': 'Visit /api/docs/ for interactive API documentation'
    })

urlpatterns = [
    path('', api_root, name='api-root'),
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')), # Add the language switching URL pattern
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema')),
    path('metrics/', ExportToDjangoView, name='prometheus-metrics'),  # Prometheus metrics endpoint
    # ── ERP (HR + internal-ops) v1 namespace ──
    path('api/v1/auth/', include(('authmanagement.urls', 'auth'), namespace='v1-auth')),
    path('api/v1/business/', include(('business.urls', 'business'), namespace='v1-business')),
    path('api/v1/core/', include(('core.urls', 'core'), namespace='v1-core')),
    path('api/v1/integrations/', include(('integrations.urls', 'integrations'), namespace='v1-integrations')),
    path('api/v1/hrm/', include(('hrm.urls', 'hrm'), namespace='v1-hrm')),
    path('api/v1/approvals/', include(('approvals.urls', 'approvals'), namespace='v1-approvals')),
    path('api/v1/addresses/', include(('addresses.urls', 'addresses'), namespace='v1-addresses')),

    # Centralized system apps
    path('api/v1/tasks/', include(('task_management.urls', 'task-management'), namespace='v1-task-management')),
    path('api/v1/errors/', include(('error_handling.urls', 'error-handling'), namespace='v1-error-handling')),
    path('api/v1/cache/', include(('caching.urls', 'caching'), namespace='v1-caching')),

    # ── Decomposed out (now owned by their microservices; routes removed) ──
    # assets/products/stock/vendor/procurement/manufacturing → inventory-api
    # finance/* + payments + taxes                           → treasury-api
    # crm/*                                                   → marketflow
    # ecommerce.cart/order                                   → ordering-backend
    # ecommerce.pos                                          → pos-api
    # notifications                                          → notifications-api
    # core_orders                                            → retired
]

# Serve media files in all environments (including production)
# Django's static() only works when DEBUG=True, so we add custom serving for production
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
else:
    # Production media serving (WhiteNoise handles static files automatically)
    from django.views.static import serve
    from django.urls import re_path
    
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
    ]
# default: "Django Administration"
admin.site.site_header = 'ProcureProKE'
# default: "Site administration"
admin.site.index_title = 'ProcureProKE'
admin.site.site_title = 'ProcureProKE'

# scheduler = BackgroundScheduler()
# scheduler.add_job(check_expiring_contracts, 'interval', days=1)  # Run daily
# scheduler.start()