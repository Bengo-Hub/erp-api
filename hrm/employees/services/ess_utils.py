"""
ESS (Employee Self-Service) Utilities
Handles ESS account creation, activation, and email notifications
"""

import secrets
import string
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.conf import settings
from notifications.services.email_service import EmailService

User = get_user_model()


def generate_temporary_password(length=12):
    """Generate a secure temporary password"""
    characters = string.ascii_letters + string.digits + "!@#$%"
    password = ''.join(secrets.choice(characters) for _ in range(length))
    return password


def create_ess_account(employee):
    """
    Create ESS account for employee
    - Sets allow_ess = True
    - Records activation timestamp
    - Sets temporary password for user
    - Forces password change on first login (except superusers)
    - Sends welcome email with credentials
    """
    if not employee.allow_ess:
        return {
            'success': False,
            'message': 'ESS access not enabled for this employee'
        }
    
    user = employee.user
    
    # Use standard password for consistency or generate random
    temp_password = "ChangeMe123!"  # Standardized password
    user.set_password(temp_password)
    
    # Force password change on first login (except for superusers)
    if not user.is_superuser:
        user.must_change_password = True
    
    user.save()
    
    # Update ESS activation timestamp
    if not employee.ess_activated_at:
        employee.ess_activated_at = timezone.now()
        employee.save()
    
    # Send welcome email
    email_sent = send_welcome_email(employee, temp_password)
    
    return {
        'success': True,
        'message': 'ESS account created successfully',
        'email_sent': email_sent,
        'temporary_password': temp_password
    }


def send_welcome_email(employee, temporary_password):
    """Send welcome email to employee with ESS login credentials"""
    try:
        # Get employee details
        user = employee.user
        organisation = employee.organisation
        
        # Get HR details if available
        hr_details = employee.hr_details.first() if employee.hr_details.exists() else None
        
        # Prepare context for email template
        context = {
            'business_name': organisation.name if organisation else 'BengoBox ERP',
            'employee_name': f"{user.first_name} {user.last_name}",
            'email': user.email,
            'temporary_password': temporary_password,
            'employee_number': hr_details.job_or_staff_number if hr_details else 'N/A',
            'job_title': hr_details.job_title if hr_details else 'N/A',
            'department': hr_details.department.name if hr_details and hr_details.department else 'N/A',
            'employment_date': hr_details.date_of_employment if hr_details else 'N/A',
            'employment_type': employee.salary_details.first().employment_type if employee.salary_details.exists() else 'N/A',
            'ess_portal_url': getattr(settings, 'FRONTEND_URL', 'http://localhost:5173') + '/ess',
            'current_year': timezone.now().year
        }
        
        # Prepare subject
        subject = f"Welcome to {context['business_name']} - ESS Portal Access"
        
        # Use centralized EmailService with Django template
        email_service = EmailService()
        result = email_service.send_django_template_email(
            template_name='welcome_email.html',
            context=context,
            subject=subject,
            recipient_list=user.email,
            async_send=False  # Send synchronously for immediate feedback
        )
        
        return result.get('success', False)
        
    except Exception as e:
        print(f"Error sending welcome email: {str(e)}")
        return False


def reset_ess_password(employee, new_password=None):
    """
    Reset ESS password for employee (Admin function)
    If new_password is None, generates a temporary one
    """
    user = employee.user
    
    if new_password is None:
        new_password = generate_temporary_password()
    
    user.set_password(new_password)
    user.save()
    
    return {
        'success': True,
        'temporary_password': new_password
    }


def deactivate_ess_account(employee):
    """Deactivate ESS access for employee"""
    employee.allow_ess = False
    employee.save()
    
    return {
        'success': True,
        'message': 'ESS access deactivated'
    }
