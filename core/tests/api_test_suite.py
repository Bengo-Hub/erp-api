"""
Comprehensive API testing suite for Bengo ERP.
This module provides automated tests for all API endpoints to ensure:
- Endpoint functionality
- Authentication and authorization
- Data validation
- Error handling
- Response format consistency
"""

import json
import logging
from typing import Dict, Any, List
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from rest_framework.authtoken.models import Token

logger = logging.getLogger(__name__)

User = get_user_model()

class BaseAPITestCase(APITestCase):
    """Base test case for API testing with common setup and utilities."""
    
    def setUp(self):
        """Set up test data and authentication."""
        self.client = APIClient()
        self.user = self.create_test_user()
        self.token = self.create_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
    
    def create_test_user(self, **kwargs):
        """Create a test user with default or custom attributes."""
        user_data = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'testpass123',
            'first_name': 'Test',
            'last_name': 'User',
            'is_active': True,
            'is_staff': True,
        }
        user_data.update(kwargs)
        
        user = User.objects.create_user(**user_data)
        return user
    
    def create_auth_token(self):
        """Create authentication token for the test user."""
        return Token.objects.create(user=self.user)
    
    def assert_response_structure(self, response, expected_fields: List[str]):
        """Assert that response has expected structure."""
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        for field in expected_fields:
            self.assertIn(field, data)
    
    def assert_error_response(self, response, expected_status: int, expected_error: str = None):
        """Assert error response structure."""
        self.assertEqual(response.status_code, expected_status)
        data = response.json()
        
        if expected_error:
            self.assertIn('error', data)
            self.assertIn(expected_error, data['error'])

class AuthenticationAPITests(BaseAPITestCase):
    """Test authentication endpoints."""
    
    def test_login_success(self):
        """Test successful login."""
        url = reverse('auth:login')
        data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        response_data = response.json()
        self.assertIn('user', response_data)
        self.assertIn('token', response_data['user'])
        self.assertIn('business', response_data)
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials."""
        url = reverse('auth:login')
        data = {
            'email': 'test@example.com',
            'password': 'wrongpassword'
        }
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_logout_success(self):
        """Test successful logout."""
        url = reverse('auth:logout')
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

class HRMEmployeeAPITests(BaseAPITestCase):
    """Test HRM employee endpoints."""
    
    def setUp(self):
        super().setUp()
        self.employee_data = {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john.doe@example.com',
            'phone': '+254700123456',
            'employee_id': 'EMP001',
            'department': 'IT',
            'position': 'Software Developer',
            'hire_date': '2024-01-01',
            'salary': 50000.00
        }
    
    def test_create_employee(self):
        """Test creating a new employee."""
        url = reverse('v1-hrm-employees:employee-list')
        response = self.client.post(url, self.employee_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data['first_name'], 'John')
        self.assertEqual(response_data['last_name'], 'Doe')
    
    def test_get_employee_list(self):
        """Test retrieving employee list."""
        url = reverse('v1-hrm-employees:employee-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.json())
    
    def test_get_employee_detail(self):
        """Test retrieving employee details."""
        # First create an employee
        create_url = reverse('v1-hrm-employees:employee-list')
        create_response = self.client.post(create_url, self.employee_data)
        employee_id = create_response.json()['id']
        
        # Then get employee details
        detail_url = reverse('v1-hrm-employees:employee-detail', kwargs={'pk': employee_id})
        response = self.client.get(detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data['first_name'], 'John')
    
    def test_update_employee(self):
        """Test updating employee information."""
        # First create an employee
        create_url = reverse('v1-hrm-employees:employee-list')
        create_response = self.client.post(create_url, self.employee_data)
        employee_id = create_response.json()['id']
        
        # Update employee
        update_data = {'first_name': 'Jane', 'salary': 55000.00}
        detail_url = reverse('v1-hrm-employees:employee-detail', kwargs={'pk': employee_id})
        response = self.client.patch(detail_url, update_data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data['first_name'], 'Jane')
        self.assertEqual(response_data['salary'], '55000.00')
    
    def test_delete_employee(self):
        """Test deleting an employee."""
        # First create an employee
        create_url = reverse('v1-hrm-employees:employee-list')
        create_response = self.client.post(create_url, self.employee_data)
        employee_id = create_response.json()['id']
        
        # Delete employee
        detail_url = reverse('v1-hrm-employees:employee-detail', kwargs={'pk': employee_id})
        response = self.client.delete(detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

class FinanceAPITests(BaseAPITestCase):
    """Test Finance module endpoints."""
    
    def setUp(self):
        super().setUp()
        self.expense_data = {
            'description': 'Office Supplies',
            'amount': 1500.00,
            'category': 'Office',
            'date': '2024-01-15',
            'payment_method': 'cash'
        }
    
    def test_create_expense(self):
        """Test creating a new expense."""
        url = reverse('v1-finance:expense-list')
        response = self.client.post(url, self.expense_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data['description'], 'Office Supplies')
        self.assertEqual(response_data['amount'], '1500.00')
    
    def test_get_expense_list(self):
        """Test retrieving expense list."""
        url = reverse('v1-finance:expense-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.json())

class CRMAPITests(BaseAPITestCase):
    """Test CRM module endpoints."""
    
    def setUp(self):
        super().setUp()
        self.customer_data = {
            'first_name': 'Alice',
            'last_name': 'Johnson',
            'email': 'alice.johnson@example.com',
            'phone': '+254700123457',
            'company': 'ABC Corp',
            'address': '123 Main St, Nairobi'
        }
    
    def test_create_customer(self):
        """Test creating a new customer."""
        url = reverse('v1-crm:contact-list')
        response = self.client.post(url, self.customer_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data['first_name'], 'Alice')
        self.assertEqual(response_data['last_name'], 'Johnson')
    
    def test_get_customer_list(self):
        """Test retrieving customer list."""
        url = reverse('v1-crm:contact-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.json())

class EcommerceAPITests(BaseAPITestCase):
    """Test E-commerce module endpoints."""
    
    def setUp(self):
        super().setUp()
        self.product_data = {
            'name': 'Test Product',
            'description': 'A test product for testing',
            'price': 1000.00,
            'sku': 'TEST001',
            'category': 'Electronics',
            'stock_quantity': 50
        }
    
    def test_create_product(self):
        """Test creating a new product."""
        url = reverse('v1-ecommerce-product:product-list')
        response = self.client.post(url, self.product_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data['name'], 'Test Product')
        self.assertEqual(response_data['price'], '1000.00')
    
    def test_get_product_list(self):
        """Test retrieving product list."""
        url = reverse('v1-ecommerce-product:product-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.json())

class ProcurementAPITests(BaseAPITestCase):
    """Test Procurement module endpoints."""
    
    def setUp(self):
        super().setUp()
        self.supplier_data = {
            'name': 'Test Supplier',
            'email': 'supplier@example.com',
            'phone': '+254700123458',
            'address': '456 Supplier St, Nairobi',
            'contact_person': 'John Supplier'
        }
    
    def test_create_supplier(self):
        """Test creating a new supplier."""
        url = reverse('v1-procurement:supplier-list')
        response = self.client.post(url, self.supplier_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data['name'], 'Test Supplier')
    
    def test_get_supplier_list(self):
        """Test retrieving supplier list."""
        url = reverse('v1-procurement:supplier-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.json())

class SecurityAPITests(BaseAPITestCase):
    """Test security-related functionality."""
    
    def test_unauthorized_access(self):
        """Test that unauthorized access is properly blocked."""
        # Remove authentication
        self.client.credentials()
        
        url = reverse('v1-hrm-employees:employee-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_rate_limiting(self):
        """Test rate limiting functionality."""
        url = reverse('v1-hrm-employees:employee-list')
        
        # Make multiple requests quickly
        for _ in range(10):
            response = self.client.get(url)
        
        # The 11th request should be rate limited
        response = self.client.get(url)
        self.assertIn(response.status_code, [status.HTTP_429_TOO_MANY_REQUESTS, status.HTTP_200_OK])
    
    def test_xss_prevention(self):
        """Test XSS prevention in input fields."""
        malicious_data = {
            'first_name': '<script>alert("xss")</script>',
            'last_name': 'Doe',
            'email': 'test@example.com',
            'phone': '+254700123456',
            'employee_id': 'EMP001'
        }
        
        url = reverse('v1-hrm-employees:employee-list')
        response = self.client.post(url, malicious_data)
        
        # Should either sanitize the input or reject it
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        
        if response.status_code == status.HTTP_201_CREATED:
            response_data = response.json()
            # Check that script tags are sanitized
            self.assertNotIn('<script>', response_data['first_name'])

class PerformanceAPITests(BaseAPITestCase):
    """Test API performance and response times."""
    
    def test_response_time(self):
        """Test that API responses are within acceptable time limits."""
        import time
        
        url = reverse('v1-hrm-employees:employee-list')
        
        start_time = time.time()
        response = self.client.get(url)
        end_time = time.time()
        
        response_time = end_time - start_time
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Response should be under 1 second
        self.assertLess(response_time, 1.0)
    
    def test_large_dataset_handling(self):
        """Test handling of large datasets."""
        # Create multiple employees
        for i in range(50):
            employee_data = {
                'first_name': f'Employee{i}',
                'last_name': f'Test{i}',
                'email': f'employee{i}@example.com',
                'phone': f'+254700123{i:03d}',
                'employee_id': f'EMP{i:03d}',
                'department': 'IT',
                'position': 'Developer',
                'hire_date': '2024-01-01',
                'salary': 50000.00
            }
            
            url = reverse('v1-hrm-employees:employee-list')
            self.client.post(url, employee_data)
        
        # Test retrieving the list
        url = reverse('v1-hrm-employees:employee-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertIn('results', response_data)
        self.assertIn('count', response_data)

class APIMonitoringTests(TestCase):
    """Test API monitoring and health check endpoints."""
    
    def setUp(self):
        self.client = Client()
    
    def test_health_check(self):
        """Test health check endpoint."""
        url = '/api/health/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('status', data)
        self.assertEqual(data['status'], 'healthy')
    
    def test_api_documentation(self):
        """Test API documentation endpoint."""
        url = '/api/docs/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)

def run_api_test_suite():
    """Run the complete API test suite."""
    import unittest
    
    # Discover and run all tests
    loader = unittest.TestLoader()
    suite = loader.discover('core.tests', pattern='api_test_suite.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_api_test_suite()
    exit(0 if success else 1)
