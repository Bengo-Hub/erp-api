from django.test import TestCase
from rest_framework.test import APIClient
from business.models import Bussiness, BusinessLocation
from ecommerce.product.models import Products
from ecommerce.stockinventory.models import StockInventory, Branch, Unit


class ProductTimezoneSerializationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.location = BusinessLocation.objects.create(city='TestCity')
        self.business = Bussiness.objects.create(name='TZBusiness', owner_id=1, location=self.location, timezone='Africa/Nairobi')
        self.branch = Branch.objects.create(business=self.business, location=self.location, name='Main')
        self.product = Products.objects.create(title='TZ Product', product_type='goods', default_price=100.00, business=self.business)
        Unit.objects.get_or_create(title='Piece(s)')
        StockInventory.objects.create(product=self.product, branch=self.branch, stock_level=5, selling_price=120.00)

    def test_products_list_serializes_business_timezone_as_string(self):
        resp = self.client.get('/api/v1/ecommerce/product/products/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # results may be nested under 'results' depending on pagination
        items = data.get('results') if isinstance(data, dict) and 'results' in data else data
        # Ensure at least one product returned and timezone is string where present
        self.assertTrue(len(items) >= 1)
        found = False
        for item in items:
            prod = item.get('product') or item
            business = prod.get('business') if isinstance(prod, dict) else None
            if business:
                tz = business.get('timezone')
                # Should be a string (or None)
                self.assertTrue(tz is None or isinstance(tz, str))
                found = True
        self.assertTrue(found, 'No business objects found in product list response')
