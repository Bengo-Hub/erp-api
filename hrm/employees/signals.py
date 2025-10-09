from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import SalaryDetails
from hrm.payroll.models import *


@receiver(post_save, sender=SalaryDetails)
def auto_create_statutory_deductions(sender, instance, created, **kwargs):
    """
    Automatically create statutory deductions when a new employee is created.
    """
    if created:  # Only run the code when a new employee is created
        # Get active statutory deductions
        statutory_deductions = PayrollComponents.objects.filter(category='Deductions', statutory=True, is_active=True)
        
        for deduction in statutory_deductions:
            # Check if the deduction is NHIF and the employee is eligible for NHIF
            if  deduction.mode=='monthly':
                Deductions.objects.get_or_create(employee=instance.employee, deduction=deduction)
