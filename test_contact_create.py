#!/usr/bin/env python
"""Test script to validate contact creation with headers."""
import os
import sys
import django
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ProcureProKEAPI.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from crm.contacts.views import ContactsViewSet
from rest_framework.request import Request

User = get_user_model()

def test_contact_create():
    """Test creating a contact with header-provided branch/business IDs."""
    factory = RequestFactory()
    
    # Create a mock request with branch/business headers
    django_request = factory.post(
        '/api/v1/crm/contacts/',
        data=json.dumps({
            'contact_type': 'Suppliers',
            'account_type': 'Business',
            'contact_id': 'TEST-SUPPLIER-001',
            'first_name': 'Test',
            'last_name': 'Supplier',
            'business': 'Test Business Ltd',
            'phone': '+254700000001',
            'alternative_contact': '+254700000002'
        }),
        content_type='application/json',
        HTTP_X_BRANCH_ID='1',
        HTTP_X_BUSINESS_ID='1'
    )
    
    # Wrap in DRF Request
    request = Request(django_request)
    
    # Get or create a test user
    try:
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            print("Creating test superuser...")
            user = User.objects.create_superuser('testadmin', 'test@test.com', 'test123')
        request.user = user
        print(f"✓ Using user: {user.username}")
        
        # Test the viewset
        viewset = ContactsViewSet()
        viewset.request = request
        viewset.format_kwarg = None
        
        print("\n📝 Testing contact creation with headers...")
        print(f"   Headers: X-Branch-ID={django_request.META.get('HTTP_X_BRANCH_ID')}, X-Business-ID={django_request.META.get('HTTP_X_BUSINESS_ID')}")
        
        response = viewset.create(request)
        print(f"\n✓ Response status: {response.status_code}")
        
        if response.status_code in [201, 200]:
            print("✓ Contact created successfully!")
            print(f"   Data keys: {list(response.data.keys())}")
            if 'contact_id' in response.data:
                print(f"   Contact ID: {response.data.get('contact_id')}")
            return True
        else:
            print(f"✗ Creation failed with status {response.status_code}")
            print(f"   Response: {response.data}")
            return False
        
    except Exception as e:
        print(f"\n✗ Error during test: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_contact_create()
    sys.exit(0 if success else 1)
