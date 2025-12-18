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
    # Public routes (no authentication required) - must be before versioned API routes
    path('', include(('finance.invoicing.public_urls', 'public'), namespace='public')),
    path('metrics/', ExportToDjangoView, name='prometheus-metrics'),  # Prometheus metrics endpoint
    # v1 namespace 
    # v1 namespace
    path('api/v1/auth/', include(('authmanagement.urls', 'auth'), namespace='v1-auth')),
    path('api/v1/', include(('assets.urls', 'assets'), namespace='v1-assets')),
    path('api/v1/business/', include(('business.urls', 'business'), namespace='v1-business')),
    path('api/v1/core/', include(('core.urls', 'core'), namespace='v1-core')),
    path('api/v1/crm/', include(('crm.contacts.urls', 'crm'), namespace='v1-crm')),
    path('api/v1/crm/', include(('crm.leads.urls', 'crm-leads'), namespace='v1-crm-leads')),
    path('api/v1/crm/pipeline/', include(('crm.pipeline.urls', 'crm-pipeline'), namespace='v1-crm-pipeline')),
    path('api/v1/crm/', include(('crm.campaigns.urls', 'crm-campaigns'), namespace='v1-crm-campaigns')),
    path('api/v1/integrations/', include(('integrations.urls', 'integrations'), namespace='v1-integrations')),
    path('api/v1/notifications/', include(('notifications.urls', 'notifications'), namespace='v1-notifications')),
    path('api/v1/ecommerce/pos/', include(('ecommerce.pos.urls', 'ecommerce-pos'), namespace='v1-ecommerce-pos')),
    path('api/v1/ecommerce/cart/', include(('ecommerce.cart.urls', 'ecommerce-cart'), namespace='v1-ecommerce-cart')),
    path('api/v1/ecommerce/product/', include(('ecommerce.product.urls', 'ecommerce-product'), namespace='v1-ecommerce-product')),
    path('api/v1/ecommerce/order/', include(('ecommerce.order.urls', 'ecommerce-order'), namespace='v1-ecommerce-order')),
    path('api/v1/ecommerce/stockinventory/', include(('ecommerce.stockinventory.urls', 'ecommerce-stock'), namespace='v1-ecommerce-stock')),
    path('api/v1/ecommerce/vendor/', include(('ecommerce.vendor.urls', 'ecommerce-vendor'), namespace='v1-ecommerce-vendor')),
    path('api/v1/ecommerce/analytics/', include(('ecommerce.analytics.urls', 'ecommerce-analytics'), namespace='v1-ecommerce-analytics')),
    path('api/v1/finance/accounts/', include(('finance.accounts.urls', 'finance-accounts'), namespace='v1-finance-accounts')),
    path('api/v1/finance/', include(('finance.expenses.urls', 'finance-expenses'), namespace='v1-finance-expenses')),
    path('api/v1/finance/taxes/', include(('finance.taxes.urls', 'finance-taxes'), namespace='v1-finance-taxes')),
    path('api/v1/finance/payment/', include(('finance.payment.urls', 'finance-payment'), namespace='v1-finance-payment')),
    path('api/v1/finance/', include(('finance.budgets.urls', 'finance-budgets'), namespace='v1-finance-budgets')),
    path('api/v1/finance/cashflow/', include(('finance.cashflow.urls', 'finance-cashflow'), namespace='v1-finance-cashflow')),
    path('api/v1/finance/reconciliation/', include(('finance.reconciliation.urls', 'finance-reconciliation'), namespace='v1-finance-reconciliation')),
    path('api/v1/finance/', include(('finance.urls', 'finance-analytics'), namespace='v1-finance-analytics')),
    path('api/v1/hrm/', include(('hrm.urls', 'hrm'), namespace='v1-hrm')),
    path('api/v1/manufacturing/', include(('manufacturing.urls', 'manufacturing'), namespace='v1-manufacturing')),
    path('api/v1/procurement/', include(('procurement.purchases.urls', 'procurement-purchases'), namespace='v1-procurement-purchases')),
    path('api/v1/procurement/', include(('procurement.requisitions.urls', 'procurement-requisitions'), namespace='v1-procurement-requisitions')),
    path('api/v1/procurement/', include(('procurement.orders.urls', 'procurement-orders'), namespace='v1-procurement-orders')),
    path('api/v1/procurement/', include(('procurement.supplier_performance.urls', 'supplier-performance'), namespace='v1-supplier-performance')),
    path('api/v1/procurement/', include(('procurement.contracts.urls', 'procurement-contracts'), namespace='v1-procurement-contracts')),
    # Centralized apps
    path('api/v1/orders/', include(('core_orders.urls', 'core-orders'), namespace='v1-core-orders')),
    path('api/v1/approvals/', include(('approvals.urls', 'approvals'), namespace='v1-approvals')),
    path('api/v1/addresses/', include(('addresses.urls', 'addresses'), namespace='v1-addresses')),
    
    # Centralized system apps
    path('api/v1/tasks/', include(('task_management.urls', 'task-management'), namespace='v1-task-management')),
    path('api/v1/errors/', include(('error_handling.urls', 'error-handling'), namespace='v1-error-handling')),
    path('api/v1/cache/', include(('caching.urls', 'caching'), namespace='v1-caching')),
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