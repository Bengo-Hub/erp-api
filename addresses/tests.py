from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from .models import AddressBook


class AddressBookAPITests(TestCase):
	def setUp(self):
		User = get_user_model()
		self.user = User.objects.create_user(username='testuser', password='pass')
		self.client = APIClient()
		self.client.force_authenticate(self.user)

	def test_get_addresses_with_contact_param_returns_ok(self):
		# Create an address for the user
		addr = AddressBook.objects.create(
			user=self.user,
			first_name='Test',
			last_name='User',
			phone='+254700000000',
			county='Nairobi',
			street_name='Test Street',
			postal_code='00100'
		)

		# Call list endpoint with an unrelated 'contact' param (frontend may send this)
		resp = self.client.get('/api/v1/addresses/addresses/', {'contact': 999})
		self.assertEqual(resp.status_code, 200)
		# Ensure our address appears in results
		data = resp.data
		# when paginated, results key may be present
		results = data.get('results', data)
		self.assertTrue(any(a.get('id') == addr.id for a in results))

