from rest_framework.routers import DefaultRouter
from .views import BudgetViewSet, BudgetLineViewSet

router = DefaultRouter()
router.register(r'budgets', BudgetViewSet, basename='budgets')
router.register(r'budget-lines', BudgetLineViewSet, basename='budget-lines')

urlpatterns = router.urls
