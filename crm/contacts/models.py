from django.db import models
from django.contrib.auth.models import Group
from business.models import Bussiness, Branch
from django.utils import timezone
from django.contrib.auth import get_user_model
from decimal import Decimal

User = get_user_model()
    
class CustomerGroup(models.Model):
    group_name=models.CharField(max_length=100,blank=True,null=True)
    dicount_calculation=models.CharField(max_length=100,choices=[("Percentage","Percentage"),("Fixed","Fixed")])
    amount=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'))
    
    class Meta:
        db_table="customer_groups"
        managed = True
        verbose_name_plural = "Customer Groups"
        indexes = [
            models.Index(fields=['group_name'], name='idx_customer_group_name'),
            models.Index(fields=['dicount_calculation'], name='idx_customer_group_discount'),
        ]

    def __str__(self) -> str:
        return self.group_name or "Unnamed Group"
    
class Contact(models.Model):
    contact_id=models.CharField(max_length=100)
    contact_type=models.CharField(max_length=100,choices=[("Suppliers","Suppliers"),("Customers","Customers"),("Customers & Suppliers","Customers & Suppliers")],default='Customers')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contacts')
    business = models.ForeignKey(Bussiness, on_delete=models.SET_NULL, null=True, blank=True, related_name='contacts', help_text='Business this contact belongs to')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, help_text='Branch where this contact is managed')
    designation=models.CharField(max_length=100,help_text='Mr/Mrs/Ms')
    customer_group=models.ForeignKey(CustomerGroup,on_delete=models.SET_NULL,blank=True,null=True,default=None)
    account_type=models.CharField(max_length=100,choices=[("Individual","Individual"),("Business","Business")],default='Individual')
    tax_number=models.CharField(max_length=100,blank=True,null=True,help_text='Tax Number if a business')
    business_name=models.CharField(max_length=100,blank=True,null=True,help_text='Business Name if a business')
    business_address=models.CharField(max_length=100,blank=True,null=True, help_text='Business Address if a business')
    alternative_contact=models.CharField(max_length=15,blank=True,null=True)
    phone=models.CharField(max_length=15,blank=True,null=True)
    landline=models.CharField(max_length=15,blank=True,null=True,help_text='Landline phone number')
    credit_limit=models.DecimalField(max_digits=14,decimal_places=2,default=None,blank=True,null=True)
    added_on=models.DateField(default=timezone.now)
    is_deleted=models.BooleanField(default=False)
    created_by=models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_contacts')
    
    class Meta:
        db_table="contacts"
        managed = True
        verbose_name_plural = "Contacts"
        indexes = [
            models.Index(fields=['contact_id'], name='idx_contact_id'),
            models.Index(fields=['contact_type'], name='idx_contact_type'),
            models.Index(fields=['user'], name='idx_contact_user'),
            models.Index(fields=['business'], name='idx_contact_business'),
            models.Index(fields=['branch'], name='idx_contact_branch'),
            models.Index(fields=['customer_group'], name='idx_contact_customer_group'),
            models.Index(fields=['account_type'], name='idx_contact_account_type'),
            models.Index(fields=['phone'], name='idx_contact_phone'),
            models.Index(fields=['is_deleted'], name='idx_contact_deleted'),
            models.Index(fields=['added_on'], name='idx_contact_added_on'),
        ]
    
    def __str__(self) -> str:
        if self.user:
            return f"{self.user.username} - {self.user.first_name} {self.user.last_name}"
        return f"Contact {self.contact_id}"
    
    @property
    def location(self):
        """Get location from branch for backward compatibility"""
        return self.branch.location if self.branch else None
    
    def save(self,*args,**kwargs):
        super().save(*args,**kwargs)
        # Create contact account if it doesn't exist
        # Use a try-except to avoid circular import issues
        try:
            if not hasattr(self, 'accounts') or not self.accounts.first():
                from .models import ContactAccount
                ContactAccount.objects.get_or_create(contact=self)
        except Exception:
            # If there's an error creating the account, just continue
            pass

class ContactAccount(models.Model):
    contact=models.ForeignKey(Contact,on_delete=models.CASCADE,related_name='accounts')
    account_balance=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'))#opening balance
    advance_balance=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'))#advance balance
    total_sale_due=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'))
    total_sale_return_due=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'))

    class Meta:
        db_table="contact_accounts"
        managed = True
        verbose_name_plural = "Account"
        indexes = [
            models.Index(fields=['contact'], name='idx_contact_account_contact'),
        ]
    def __str__(self) -> str:
        return self.contact.user.email if self.contact and self.contact.user else "Unknown Account"
    

