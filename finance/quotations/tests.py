from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from business.models import Bussiness, Branch, BusinessLocation
from crm.contacts.models import Contact
from ecommerce.product.models import Products
from django.contrib.auth import get_user_model


class QuotationAPITests(APITestCase):
	def setUp(self):
		self.client = APIClient()
		User = get_user_model()
		self.user = User.objects.create_user(username='apitest', email='apitest@example.com', password='testpass')
		self.client.force_authenticate(user=self.user)

	def test_create_quotation_with_items(self):
		# Create business, location and branch
		loc = BusinessLocation.objects.create(city='Nairobi')
		business = Bussiness.objects.create(owner=self.user, name='TestCo', location=loc)
		branch = Branch.objects.create(business=business, location=loc, name='Main', branch_code='MB001')

		# Create customer contact
		customer_user = self.user
		contact = Contact.objects.create(contact_id='CUST-1', user=customer_user, designation='Mr', created_by=self.user, business=business)

		# Create product
		product = Products.objects.create(title='Service Test', business=business, product_type='service', default_price=10000)

		url = '/api/v1/finance/quotations/quotations/'
		payload = {
			'customer': contact.id,
			'branch': branch.id,
			'quotation_date': timezone.now().date().isoformat(),
			'validity_period': '30_days',
			'introduction': 'Thank you',
			'customer_notes': 'Notes',
			'terms_and_conditions': 'T&C',
			'discount_type': 'percentage',
			'discount_value': 0,
			'subtotal': 10000,
			'tax_amount': 1600,
			'discount_amount': 0,
			'shipping_cost': 0,
			'total': 11600,
			'items': [
				{
					'description': 'service test',
					'quantity': 1,
					'unit_price': 10000,
					'tax_rate': 16,
					'tax_amount': 1600,
					'subtotal': 10000,
					'total': 11600,
					'product_id': product.id
				}
			]
		}

		response = self.client.post(url, payload, format='json')
		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		data = response.json().get('data')
		self.assertIsNotNone(data)
		self.assertIn('items', data)
		self.assertEqual(len(data['items']), 1)

	def test_convert_to_invoice(self):
		# Create business, location and branch
		loc = BusinessLocation.objects.create(city='Nairobi')
		business = Bussiness.objects.create(owner=self.user, name='TestCo', location=loc)
		branch = Branch.objects.create(business=business, location=loc, name='Main', branch_code='MB002')

		# Create customer contact
		customer_user = self.user
		contact = Contact.objects.create(contact_id='CUST-2', user=customer_user, designation='Mr', created_by=self.user, business=business)

		# Create product
		product = Products.objects.create(title='Service Test', business=business, product_type='service', default_price=10000)

		# Create quotation
		url = '/api/v1/finance/quotations/quotations/'
		payload = {
			'customer': contact.id,
			'branch': branch.id,
			'quotation_date': timezone.now().date().isoformat(),
			'validity_period': '30_days',
			'introduction': 'Thank you',
			'customer_notes': 'Notes',
			'terms_and_conditions': 'T&C',
			'discount_type': 'percentage',
			'discount_value': 0,
			'subtotal': 10000,
			'tax_amount': 1600,
			'discount_amount': 0,
			'shipping_cost': 0,
			'total': 11600,
			'items': [
				{
					'description': 'service test',
					'quantity': 1,
					'unit_price': 10000,
					'tax_rate': 16,
					'tax_amount': 1600,
					'subtotal': 10000,
					'total': 11600,
					'product_id': product.id
				}
			]
		}

		response = self.client.post(url, payload, format='json')
		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		quotation = response.json().get('data')
		self.assertIsNotNone(quotation)

		# Convert to invoice
		convert_url = f"/api/v1/finance/quotations/quotations/{quotation['id']}/convert-to-invoice/"
		convert_payload = {
			'payment_terms': 'net_30',
			'invoice_date': timezone.now().date().isoformat(),
			'custom_message': 'test'
		}

		convert_resp = self.client.post(convert_url, convert_payload, format='json')
		self.assertEqual(convert_resp.status_code, status.HTTP_200_OK)
		data = convert_resp.json().get('data')
		self.assertIn('invoice', data)

	def test_generate_pdf_preview(self):
		# Create business/branch/customer/product and quotation
		loc = BusinessLocation.objects.create(city='Nairobi')
		business = Bussiness.objects.create(owner=self.user, name='TestCo', location=loc)
		branch = Branch.objects.create(business=business, location=loc, name='Main', branch_code='MB003')

		contact = Contact.objects.create(contact_id='CUST-3', user=self.user, designation='Mr', created_by=self.user, business=business)
		product = Products.objects.create(title='Service PDF', business=business, product_type='service', default_price=5000)

		url = '/api/v1/finance/quotations/quotations/'
		payload = {
			'customer': contact.id,
			'branch': branch.id,
			'quotation_date': timezone.now().date().isoformat(),
			'validity_period': '30_days',
			'subtotal': 5000,
			'tax_amount': 800,
			'total': 5800,
			'items': [
				{
					'description': 'service pdf',
					'quantity': 1,
					'unit_price': 5000,
					'tax_rate': 16,
					'tax_amount': 800,
					'subtotal': 5000,
					'total': 5800,
					'product_id': product.id
				}
			]
		}

		response = self.client.post(url, payload, format='json')
		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		quotation = response.json().get('data')

		pdf_url = f"/api/v1/finance/quotations/quotations/{quotation['id']}/pdf/"
		pdf_resp = self.client.get(pdf_url)
		self.assertEqual(pdf_resp.status_code, status.HTTP_200_OK)
		# Ensure PDF content is returned
		self.assertIn('application/pdf', pdf_resp['Content-Type'])

	def test_quotation_pdf_includes_company_address_from_hq_branch(self):
		# Create business with HQ branch but create quotation without branch
		loc = BusinessLocation.objects.create(building_name='Suite 10', street_name='Park Road', city='Nairobi', county='Nairobi', state='Nairobi State', country='Kenya')
		business = Bussiness.objects.create(owner=self.user, name='KuraWeigh Solutions Ltd', location=loc, email='procurement@kuraweigh.com')
		main = Branch.objects.create(business=business, location=loc, name='HQ', branch_code='HQ-2', is_main_branch=True, is_active=True, contact_number='+254 701 987 654')

		contact = Contact.objects.create(contact_id='CUST-PDF-2', user=self.user, designation='Mr', created_by=self.user, business=business)
		product = Products.objects.create(title='Quote PDF Test', business=business, product_type='service', default_price=7500)

		url = '/api/v1/finance/quotations/quotations/'
		payload = {
			'customer': contact.id,
			'quotation_date': timezone.now().date().isoformat(),
			'validity_period': '30_days',
			'subtotal': 7500,
			'tax_amount': 1200,
			'total': 8700,
			'items': [
				{
					'description': 'Service HQ Quote',
					'quantity': 1,
					'unit_price': 7500,
					'subtotal': 7500,
					'total': 7500,
					'product_id': product.id
				}
			]
		}

		response = self.client.post(url, payload, format='json')
		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		quotation = response.json().get('data')

		pdf_url = f"/api/v1/finance/quotations/quotations/{quotation['id']}/pdf/"
		pdf_resp = self.client.get(pdf_url)
		self.assertEqual(pdf_resp.status_code, status.HTTP_200_OK)
		pdf_bytes = pdf_resp.content

		self.assertIn(b'KuraWeigh Solutions Ltd', pdf_bytes)
		self.assertIn(b'Park Road', pdf_bytes)
		self.assertIn(b'Nairobi', pdf_bytes)
		self.assertIn(b'Kenya', pdf_bytes)
		self.assertIn(b'procurement@kuraweigh.com', pdf_bytes)
		self.assertIn(b'+254 701 987 654', pdf_bytes)

	def test_pdf_etag_and_last_modified_refresh(self):
		# Create business/branch/customer/product and quotation
		loc = BusinessLocation.objects.create(city='Nairobi')
		business = Bussiness.objects.create(owner=self.user, name='TestCo', location=loc)
		branch = Branch.objects.create(business=business, location=loc, name='Main', branch_code='MB005')

		contact = Contact.objects.create(contact_id='CUST-ETAG', user=self.user, designation='Mr', created_by=self.user, business=business)
		product = Products.objects.create(title='Service PDF ETag', business=business, product_type='service', default_price=2000)

		url = '/api/v1/finance/quotations/quotations/'
		payload = {
			'customer': contact.id,
			'branch': branch.id,
			'quotation_date': timezone.now().date().isoformat(),
			'validity_period': '30_days',
			'subtotal': 2000,
			'tax_amount': 320,
			'total': 2320,
			'items': [
				{
					'description': 'service pdf etag',
					'quantity': 1,
					'unit_price': 2000,
					'tax_rate': 16,
					'tax_amount': 320,
					'subtotal': 2000,
					'total': 2320,
					'product_id': product.id
				}
			]
		}

		response = self.client.post(url, payload, format='json')
		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		quotation = response.json().get('data')

		pdf_url = f"/api/v1/finance/quotations/quotations/{quotation['id']}/pdf/"
		# Initial fetch - should contain ETag and Last-Modified
		first = self.client.get(pdf_url)
		self.assertEqual(first.status_code, status.HTTP_200_OK)
		self.assertIn('ETag', first)
		self.assertIn('Last-Modified', first)
		old_etag = first['ETag']

		# If client sends If-None-Match with same ETag, server should respond 304 Not Modified
		not_modified = self.client.get(pdf_url, **{'HTTP_IF_NONE_MATCH': old_etag})
		self.assertEqual(not_modified.status_code, status.HTTP_304_NOT_MODIFIED)

		# Modify quotation (update a field)
		patch_url = f"/api/v1/finance/quotations/quotations/{quotation['id']}/"
		patch_resp = self.client.patch(patch_url, {'customer_notes': 'Updated for ETag test'}, format='json')
		self.assertIn(patch_resp.status_code, [status.HTTP_200_OK, status.HTTP_202_ACCEPTED])

		# Fetch again with old ETag - should now return 200 with a new ETag
		after = self.client.get(pdf_url, **{'HTTP_IF_NONE_MATCH': old_etag})
		self.assertEqual(after.status_code, status.HTTP_200_OK)
		self.assertIn('ETag', after)
		new_etag = after['ETag']
		self.assertNotEqual(old_etag, new_etag)

		# Subsequent request with latest ETag should return 304
		fresh_not_modified = self.client.get(pdf_url, **{'HTTP_IF_NONE_MATCH': new_etag})
		self.assertEqual(fresh_not_modified.status_code, status.HTTP_304_NOT_MODIFIED)

	def test_create_quotation_with_many_decimal_places(self):
		# Create business, location and branch
		loc = BusinessLocation.objects.create(city='Nairobi')
		business = Bussiness.objects.create(owner=self.user, name='TestCo', location=loc)
		branch = Branch.objects.create(business=business, location=loc, name='Main', branch_code='MB004')

		contact = Contact.objects.create(contact_id='CUST-DEC', user=self.user, designation='Mr', created_by=self.user, business=business)
		product1 = Products.objects.create(title='Service A', business=business, product_type='service', default_price=10000)
		product2 = Products.objects.create(title='Service B', business=business, product_type='service', default_price=289.96)

		url = '/api/v1/finance/quotations/quotations/'
		payload = {
			'customer': contact.id,
			'branch': branch.id,
			'quotation_date': timezone.now().date().isoformat(),
			'validity_period': '30_days',
			'subtotal': 10289.96,
			'tax_amount': 1646.3936,
			'total': 11936.353599999999,
			'items': [
				{
					'description': 'service test',
					'quantity': 1,
					'unit_price': 10000,
					'tax_rate': 16,
					'tax_amount': 1600,
					'subtotal': 10000,
					'total': 11600,
					'product_id': product1.id
				},
				{
					'description': 'Demo electronics pro',
					'quantity': 1,
					'unit_price': 289.96,
					'tax_rate': 16,
					'tax_amount': 46.3936,
					'subtotal': 289.96,
					'total': 336.3536,
					'product_id': product2.id
				}
			]
		}

		response = self.client.post(url, payload, format='json')
		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		data = response.json().get('data')
		self.assertIsNotNone(data)
		# Ensure monetary fields are quantized to 2dp
		self.assertEqual(str(data['tax_amount']), '1646.39')
		# Ensure totals are quantized correctly
		self.assertEqual(str(data['total']), '11936.35')

# Create your tests here.
