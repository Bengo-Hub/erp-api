from rest_framework.test import APIRequestFactory
from ecommerce.product.views import ProductViewSet
from django.contrib.auth import get_user_model

factory = APIRequestFactory()
request = factory.get('/api/v1/ecommerce/product/products/')
view = ProductViewSet.as_view({'get':'list'})
response = view(request)
print('status:', response.status_code)
# Print a short preview
data = response.data
print('type(data):', type(data))
if isinstance(data, dict):
    print('keys:', list(data.keys()))
    if 'data' in data and isinstance(data['data'], list):
        print('first item keys:', list(data['data'][0].keys()) if data['data'] else 'no items')
else:
    print('data length:', len(data) if hasattr(data,'__len__') else 'no len')
print('Done')
