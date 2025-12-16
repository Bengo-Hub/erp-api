from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from business.models import Bussiness, Branch, BusinessLocation


class BusinessBranchAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(username='biztest', email='biztest@example.com', password='testpass')
        self.client.force_authenticate(user=self.user)

        loc = BusinessLocation.objects.create(city='Nairobi')
        self.business = Bussiness.objects.create(owner=self.user, name='BizCo', location=loc)

    def test_create_branch_for_business(self):
        url = f"/api/v1/business/business/{self.business.id}/branches/"
        payload = {
            'name': 'New Branch',
            'branch_code': 'NB-001',
            'location': self.business.location.id,
            'is_main_branch': False
        }
        resp = self.client.post(url, payload, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
        data = resp.json()
        self.assertEqual(data.get('name'), 'New Branch')
        self.assertEqual(data.get('branch_code'), 'NB-001')
from django.test import TestCase

# Create your tests here.
