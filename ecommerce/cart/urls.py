from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CartSessionViewSet, CartItemViewSet, SavedForLaterViewSet
from .coupon_views import CouponViewSet

# Create a router and register our viewsets with it
router = DefaultRouter()
router.register(r'cart-sessions', CartSessionViewSet, basename='cart-session')
router.register(r'cart', CartItemViewSet, basename='cart')
router.register(r'saved-items', SavedForLaterViewSet, basename='saved-for-later')
router.register(r'coupons', CouponViewSet, basename='coupons')


urlpatterns = [
    path('cart/', include(router.urls)),
]
