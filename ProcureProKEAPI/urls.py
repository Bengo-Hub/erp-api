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
from apscheduler.schedulers.background import BackgroundScheduler
from hrm.employees.management.commands.tasks import check_expiring_contracts
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

# Prometheus metrics
from django_prometheus.exports import ExportToDjangoView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')), # Add the language switching URL pattern
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema')),
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
    #path('api/',include('hrm.recruitment.urls')),
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
    path('api/v1/hrm/', include(('hrm.employees.urls', 'hrm-employees'), namespace='v1-hrm-employees')),
    path('api/v1/hrm/attendance/', include(('hrm.attendance.urls', 'hrm-attendance'), namespace='v1-hrm-attendance')),
    path('api/v1/hrm/', include(('hrm.payroll.urls', 'hrm-payroll'), namespace='v1-hrm-payroll')),
    path('api/v1/hrm/leave/', include(('hrm.leave.urls', 'hrm-leave'), namespace='v1-hrm-leave')),
    path('api/v1/hrm/appraisals/', include(('hrm.appraisals.urls', 'hrm-appraisals'), namespace='v1-hrm-appraisals')),
    path('api/v1/hrm/payroll-settings/', include(('hrm.payroll_settings.urls', 'hrm-payroll-settings'), namespace='v1-hrm-payroll-settings')),
    path('api/v1/hrm/recruitment/', include(('hrm.recruitment.urls', 'hrm-recruitment'), namespace='v1-hrm-recruitment')),
    path('api/v1/hrm/training/', include(('hrm.training.urls', 'hrm-training'), namespace='v1-hrm-training')),
    path('api/v1/hrm/performance/', include(('hrm.performance.urls', 'hrm-performance'), namespace='v1-hrm-performance')),
    path('api/v1/hrm/analytics/', include(('hrm.urls', 'hrm-analytics'), namespace='v1-hrm-analytics')),
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
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
# default: "Django Administration"
admin.site.site_header = 'ProcureProKE'
# default: "Site administration"
admin.site.index_title = 'ProcureProKE'
admin.site.site_title = 'ProcureProKE'

# scheduler = BackgroundScheduler()
# scheduler.add_job(check_expiring_contracts, 'interval', days=1)  # Run daily
# scheduler.start()