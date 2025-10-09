from django.urls import path
from .views import CashFlowView

urlpatterns = [
    path('summary/', CashFlowView.as_view(), name='cashflow-summary'),
]
