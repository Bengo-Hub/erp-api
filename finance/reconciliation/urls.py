from rest_framework.routers import DefaultRouter
from .views import BankStatementLineViewSet


router = DefaultRouter()
router.register(r'bank-statements', BankStatementLineViewSet, basename='bank-statements')

urlpatterns = router.urls


