from django.test import Client
import json

c = Client()
resp = c.get('/api/v1/ecommerce/product/products/')
print('status', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    first = (data.get('results') or data.get('data') or data) if isinstance(data, dict) else data
    if isinstance(first, dict) and 'results' in first:
        first_item = first['results'][0]
    elif isinstance(first, list):
        first_item = first[0]
    else:
        first_item = first['results'][0] if 'results' in data else None
    if first_item:
        prod = first_item.get('product') or {}
        biz = prod.get('business') or {}
        print('product.business keys:', list(biz.keys()))
        print('product.business sample:', json.dumps(biz, indent=2, default=str))
    else:
        print('no items')
else:
    print('non 200')
