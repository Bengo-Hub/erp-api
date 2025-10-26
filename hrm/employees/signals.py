"""
Signals for Employee model
Auto-assign default groups and permissions to employees
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import Group
from .models import Employee
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Employee)
def assign_default_employee_group(sender, instance, created, **kwargs):
    """
    Automatically assign new employees to the 'Staff' group
    This is the default role for all employees in the ESS system
    """
    if created and instance.user:
        try:
            # Get or create the 'Staff' group
            staff_group, group_created = Group.objects.get_or_create(name='Staff')
            
            if group_created:
                logger.info("Created 'Staff' group")
            
            # Add user to the Staff group
            instance.user.groups.add(staff_group)
            logger.info(f"Assigned employee {instance.id} to 'Staff' group")
            
        except Exception as e:
            logger.error(f"Error assigning employee to Staff group: {e}")


@receiver(post_save, sender=Employee)
def activate_ess_on_allow_ess(sender, instance, created, **kwargs):
    """
    Update ESS activated timestamp when allow_ess is enabled
    """
    if instance.allow_ess and not instance.ess_activated_at:
        from django.utils import timezone
        instance.ess_activated_at = timezone.now()
        # Use update() to avoid triggering this signal again
        Employee.objects.filter(pk=instance.pk).update(ess_activated_at=instance.ess_activated_at)
        logger.info(f"ESS activated for employee {instance.id}")
