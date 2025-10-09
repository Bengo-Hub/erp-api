
from django.urls import path, include
from rest_framework import routers
from .views import *
from .utils import *

router = routers.DefaultRouter()
router.register('categories', CategoryViewSet, basename='category')
router.register('maincategories', MainCategoriesViewSet, basename='maincategory')
router.register('variations', VariationsViewSet)
router.register('products', ProductViewSet)
router.register('favourites', FavouriteViewSet,basename='favourites')
router.register('reviews', ReviewsViewSet,basename='reviews')
router.register('brands', BrandsViewSet,basename='brands')
router.register('models', ModelsViewSet,basename='models')
router.register('products-crud', ProductCRUDViewSet,basename='products-crud')


urlpatterns = [
    path('', include(router.urls)),
]
