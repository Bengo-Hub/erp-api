from django.test import TestCase

from ecommerce.stockinventory.models import StockInventory, StockTransaction
from ecommerce.product.models import Products
from procurement.purchases.models import Purchase, PurchaseItems
from business.models import Bussiness, Branch, ProductSettings
from django.contrib.auth import get_user_model

User = get_user_model()


class PurchaseStockTransactionTests(TestCase):
	def setUp(self):
		# Create minimal business and branch and product settings required by StockInventory.save()
		# Create an owner user and business that satisfies not-null constraints
		self.user = User.objects.create_user(username='testuser', email='test@example.com', password='pass')
		self.biz = Bussiness.objects.create(name='Test Biz', owner=self.user)
		ProductSettings.objects.create(business=self.biz)
		self.branch = Branch.objects.create(name='Main Branch', business=self.biz)

		# Create a product and stock inventory
		self.product = Products.objects.create(title='Test Product', business=self.biz)
		self.stock = StockInventory.objects.create(
			product=self.product,
			branch=self.branch,
			stock_level=0,
			buying_price=0,
			selling_price=0
		)

	def test_purchase_does_not_create_transaction_until_received(self):
		# Create a purchase in 'ordered' status
		purchase = Purchase.objects.create(
			purchase_id='PO-TEST-1',
			purchase_status='ordered',
			payment_status='pending',
			grand_total=100,
			branch=self.branch
		)

		PurchaseItems.objects.create(purchase=purchase, stock_item=self.stock, qty=10, unit_price=0)

		# No stock transaction should be created yet for this stock item
		self.assertFalse(StockTransaction.objects.filter(transaction_type='PURCHASE', stock_item=self.stock).exists())

		# Mark purchase as received and save (this should trigger the signal to create stock transaction)
		purchase.purchase_status = 'received'
		purchase.save()

		# Now a stock transaction for the purchase should exist
		self.assertTrue(StockTransaction.objects.filter(transaction_type='PURCHASE', stock_item=self.stock).exists())

	def test_purchase_transaction_is_idempotent(self):
		# Create a purchase and mark received
		purchase = Purchase.objects.create(
			purchase_id='PO-TEST-2',
			purchase_status='ordered',
			payment_status='pending',
			grand_total=200,
			branch=self.branch
		)
		PurchaseItems.objects.create(purchase=purchase, stock_item=self.stock, qty=5, unit_price=0)

		purchase.purchase_status = 'received'
		purchase.save()

		# One transaction should exist for this purchase and stock item
		qs = StockTransaction.objects.filter(transaction_type='PURCHASE', stock_item=self.stock, purchase=purchase)
		self.assertEqual(qs.count(), 1)

		# Saving again should not create another transaction (idempotency)
		purchase.save()
		qs2 = StockTransaction.objects.filter(transaction_type='PURCHASE', stock_item=self.stock, purchase=purchase)
		self.assertEqual(qs2.count(), 1)

	def test_cannot_create_stock_for_service_model(self):
		# Create a service product
		service = Products.objects.create(title='Consulting', business=self.biz, product_type='service', default_price=100)
		# Attempt to create stock directly should raise ValidationError
		with self.assertRaises(Exception) as cm:
			StockInventory.objects.create(product=service, branch=self.branch, stock_level=5, buying_price=100)
		self.assertIn('Stock cannot be created for service items', str(cm.exception))

	def test_cannot_create_stock_for_service_api(self):
		# Create a service product
		service = Products.objects.create(title='Consulting2', business=self.biz, product_type='service', default_price=120)
		self.client.force_login(self.user)
		payload = {
			'product': service.id,
			'branch': self.branch.id,
			'stock_level': 10,
			'buying_price': '100.00',
			'selling_price': '150.00'
		}
		response = self.client.post('/ecommerce/stockinventory/stock/', payload, content_type='application/json')
		self.assertEqual(response.status_code, 400)
		# Check response contains our validation message
		self.assertFalse(response.data.get('success', True))
		errors = response.data.get('errors', [])
		self.assertTrue(any(e['field'] == 'product' and 'service' in e['message'].lower() for e in errors))

	def test_service_appears_in_search_lite(self):
		# Create a service product
		service = Products.objects.create(title='ConsultingSearch', business=self.biz, product_type='service', default_price=200)
		self.client.force_login(self.user)
		response = self.client.get('/ecommerce/product/search-lite/', {'search': 'ConsultingSearch'})
		self.assertEqual(response.status_code, 200)
		data = response.data.get('data', [])
		# Ensure at least one service with our title is returned
		self.assertTrue(any('ConsultingSearch' in (p.get('product', {}).get('title', '') or p.get('displayName', '')) for p in data))
