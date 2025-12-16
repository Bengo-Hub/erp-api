from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from business.models import Bussiness, BusinessLocation, Branch
from crm.contacts.models import Contact
from ecommerce.product.models import Products
from django.utils import timezone

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
if not user:
    user = User.objects.create_superuser(username='apitest', email='apitest@example.com', password='testpass')

loc = BusinessLocation.objects.create(city='TestCity')
business = Bussiness.objects.create(owner=user, name='TestCo', location=loc)
branch = Branch.objects.create(business=business, location=loc, name='Main', branch_code='MBX001')
contact = Contact.objects.create(contact_id='CUST-API', user=user, designation='Mr', created_by=user, business=business)
product = Products.objects.create(title='Service test', business=business, product_type='service', default_price=10000)

client = APIClient()
client.force_authenticate(user=user)

payload = {
    "customer": contact.id,
    "branch": branch.id,
    "quotation_date": timezone.now().date().isoformat(),
    "validity_period": "30_days",
    "custom_validity_days": None,
    "introduction": "Thank you for your interest in our products/services.",
    "customer_notes": "Thank you for considering our services.",
    "terms_and_conditions": "Test",
    "discount_type": "percentage",
    "discount_value": 0,
    "subtotal": 10000,
    "tax_amount": 1600,
    "discount_amount": 0,
    "shipping_cost": 0,
    "total": 11600,
    "shipping_address": None,
    "billing_address": None,
    "items": [
        {
            "description": "service test",
            "quantity": 1,
            "unit_price": 10000,
            "tax_rate": 16,
            "tax_amount": 1600,
            "subtotal": 10000,
            "total": 11600,
            "product_id": product.id
        }
    ]
}

resp = client.post('/api/v1/finance/quotations/quotations/', payload, format='json')
print('STATUS', resp.status_code)
try:
    print(resp.json())
except Exception as e:
    print('NO JSON:', resp.content)
