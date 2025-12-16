from django.db import models,transaction
from django.utils import timezone
from decimal import Decimal
from core_orders.models import BaseOrder
from ecommerce.product.models import *
from ecommerce.pos.models import PayTerm
from crm.contacts.models import Contact
from ecommerce.stockinventory.models import StockInventory
from business.models import Bussiness, Branch, TaxRates
from addresses.models import AddressBook
from django.db.models import Sum, Q
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from core.models import BaseModel
from approvals.models import Approval

User = get_user_model()

class Purchase(models.Model):
    branch=models.ForeignKey(Branch,on_delete=models.CASCADE,related_name='purchases', blank=True, null=True)
    supplier=models.ForeignKey(Contact,on_delete=models.SET_NULL, related_name="purchases", blank=True, null=True)
    added_by = models.ForeignKey(User,on_delete=models.SET_NULL, related_name="purchases", blank=True, null=True)
    pay_term=models.ForeignKey(PayTerm,on_delete=models.SET_NULL,related_name='purchases',null=True,blank=True)
    purchase_id = models.CharField(max_length=100, blank=True, null=True)
    purchase_tax = models.DecimalField(max_digits=14,decimal_places=2, default=Decimal('0.00'),help_text="Specify precentage value")
    purchase_discount=models.DecimalField(max_digits=14,decimal_places=2, default=0.00,help_text="Specify precentage value or Fixed value")
    sub_total = models.DecimalField(max_digits=14,decimal_places=2, default=0.00,help_text="Auto calculated field. Do not fill.")
    grand_total = models.DecimalField(max_digits=14,decimal_places=2, default=0.00,help_text="Auto calculated field. Do not fill.")
    purchase_ammount = models.DecimalField(max_digits=14,decimal_places=2, default=0.00,help_text="Auto calculated field. Do not fill.")
    balance_due = models.DecimalField(max_digits=14,decimal_places=2, default=0.00,help_text="Auto calculated field. Do not fill.")
    balance_overdue=models.DecimalField(max_digits=14,decimal_places=2, default=0.00,verbose_name="Balance Owed",help_text="Auto calculated field. Do not fill.")
    date_added = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    purchase_shipping_charge=models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    additional_expenses=models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    purchase_status = models.CharField(max_length=20, choices=[("pending","Pending"),("received","Rceived"),("ordered","Ordered")],default="pending", blank=True, null=True)
    payment_status = models.CharField(max_length=20, choices=[("pending","Pending"),("due","Due"),("partial","Partial"),("paid","Paid")],default="pending", blank=True, null=True)
    paymethod = models.CharField(max_length=20,choices=(("cash","Cash"),("mpesa","Mpesa"),("card","Card")), default="cash", blank=True, null=True)
    delete_status=models.BooleanField(default=False)
    purchase_order = models.OneToOneField(BaseOrder, on_delete=models.SET_NULL,null=True, blank=True, related_name='purchase')
    workflow_status = models.CharField(max_length=20, choices=[('pending', 'Pending'),('received', 'Received'),('quality_check', 'Quality Check'),('completed', 'Completed')],default='pending')
    approvals = models.ManyToManyField(Approval, related_name='purchases', blank=True)

    def save(self, *args, **kwargs):
        is_new = not self.pk
        self.balance_due = max(Decimal(self.grand_total) - Decimal(self.purchase_ammount), Decimal(0))
        self.balance_overdue = max(Decimal(self.purchase_ammount) - Decimal(self.grand_total), Decimal(0))

        if is_new:
            super().save(*args, **kwargs)
        with transaction.atomic():
            if (self.purchase_status == 'received') and (self.payment_status in ['paid', 'partial']):
                for purchase_item in self.purchaseitems.all():
                    stock_item = purchase_item.stock_item
                    stock_item.stock_level += purchase_item.qty  # Increase stock level
                    stock_item.save()
                self.balance_due = max(self.grand_total - self.purchase_ammount, 0)
                self.balance_overdue = max(self.purchase_ammount - self.grand_total, 0)

            if not is_new:
                super().save(*args, **kwargs)

    def update_totals(self):
        """Recalculate all financial fields"""
        items_total = self.purchaseitems.aggregate(
            total=Sum('sub_total')
        )['total'] or 0
        
        self.sub_total = items_total
        tax_amount = (self.sub_total * self.purchase_tax) / 100
        discount_amount = (self.sub_total * self.purchase_discount) / 100
        self.grand_total = self.sub_total + tax_amount - discount_amount
        self.grand_total += self.purchase_shipping_charge + self.additional_expenses
        self.save()

    def __str__(self):
        return f"{self.purchase_id} - {self.grand_total}"

    class Meta:
        managed = True
        verbose_name = 'Purchases'
        verbose_name_plural = 'Purchases'
        indexes = [
            models.Index(fields=['branch'], name='idx_purchase_branch'),
            models.Index(fields=['supplier'], name='idx_purchase_supplier'),
            models.Index(fields=['added_by'], name='idx_purchase_added_by'),
            models.Index(fields=['purchase_id'], name='idx_purchase_purchase_id'),
            models.Index(fields=['date_added'], name='idx_purchase_date_added'),
            models.Index(fields=['date_updated'], name='idx_purchase_date_updated'),
            models.Index(fields=['purchase_status'], name='idx_purchase_purchase_status'),
            models.Index(fields=['payment_status'], name='idx_purchase_payment_status'),
            models.Index(fields=['paymethod'], name='idx_purchase_paymethod'),
            models.Index(fields=['delete_status'], name='idx_purchase_delete_status'),
            models.Index(fields=['purchase_order'], name='idx_purchase_purchase_order'),
            models.Index(fields=['workflow_status'], name='idx_purchase_workflow_status'),
        ]

class PurchaseItems(models.Model):
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name='purchaseitems')
    stock_item = models.ForeignKey(StockInventory,verbose_name="Purchasse Item",on_delete=models.SET_NULL,related_name='purchaseitems', null=True, blank=True)
    product = models.ForeignKey(Products, on_delete=models.SET_NULL, related_name='purchase_items', null=True, blank=True)
    qty = models.PositiveIntegerField(default=0)
    tax_amount=models.DecimalField(max_digits=14,decimal_places=2,default=0)
    discount_amount=models.DecimalField(max_digits=14,decimal_places=2,default=0,help_text="Specify precentage value or Fixed value")
    unit_price=models.DecimalField(max_digits=14,decimal_places=2,default=0,help_text="Auto calculated field. Do not fill.")
    date_added = models.DateTimeField(default=timezone.now)
    date_updated = models.DateTimeField(auto_now=True)
    sub_total=models.DecimalField(max_digits=14,decimal_places=2,default=0,help_text="Auto calculated field. Do not fill.")

    def save(self,*args,**kwargs):
        self.sub_total=float(self.unit_price)*float(self.qty)
        super().save(*args,**kwargs)

    def __str__(self):
        return f"{self.purchase.purchase_id} - {self.stock_item.product.title} {self.stock_item.variation if self.stock_item.variation else ''}"

    class Meta:
        managed = True
        verbose_name = 'Purchase Items'
        verbose_name_plural = 'Purchase Items'
        indexes = [
            models.Index(fields=['purchase'], name='idx_purchase_items_purchase'),
            models.Index(fields=['stock_item'], name='idx_purchase_items_stock_item'),
            models.Index(fields=['date_added'], name='idx_purchase_items_date_added'),
            models.Index(fields=['date_updated'], name='idx_purchase_items_updated'),
        ]

class PurchaseReturn(models.Model):
    added_by = models.ForeignKey(User,on_delete=models.SET_NULL, related_name="purchase_returns", blank=True, null=True)
    return_id = models.CharField(max_length=100, blank=True, null=True)
    original_purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='purchase_returns')
    reason = models.TextField(blank=True,null=True)
    date_returned = models.DateTimeField(auto_now_add=True)
    return_amount=models.DecimalField(max_digits=14,decimal_places=2,default=0,help_text="Auto calculated field. Do not fill.")
    return_amount_due=models.DecimalField(max_digits=14,decimal_places=2,default=0,help_text="Auto calculated field. Do not fill.")
    payment_status = models.CharField(max_length=20, choices=[("pending","Pending"),("due","Due"),("partial","Partial"),("paid","Paid")],default="pending", blank=True, null=True)

    def save(self,*args,**kwargs):
        with transaction.atomic():
            super().save(*args,**kwargs)
            returned_items_total = self.purchase_return_items.aggregate(total=Sum('sub_total'))['total'] or 0
            self.return_amount = returned_items_total
            self.return_amount_due = max(self.return_amount, 0)
            if self.payment_status == 'paid' or 'partial':
                for return_item in self.purchase_return_items.all():
                    stock_item = return_item.stock_item
                    stock_item.stock_level -= return_item.quantity  # Decrease stock level
                    stock_item.save()
                    # Recalculate grand total and balances after handling returned items
                self.return_amount_due = max(self.return_amount, 0)
            super().save(*args, **kwargs)

    class Meta:
        ordering = ['-id']
        verbose_name_plural = "Purchase Returns"
        indexes = [
            models.Index(fields=['added_by'], name='idx_purchase_return_added_by'),
            models.Index(fields=['return_id'], name='idx_purchase_return_return_id'),
            models.Index(fields=['original_purchase'], name='idx_purchase_return_original'),
            models.Index(fields=['date_returned'], name='idx_purchase_return_returned'),
            models.Index(fields=['payment_status'], name='idx_purchase_return_pay_status'),
        ]

    def __str__(self):
        return f"Sale ID:{self.original_purchase.purchase_tax} Date:{self.date_returned}"

class PurchaseReturnedItem(models.Model):
    return_record = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE,related_name='purchase_return_items')
    stock_item = models.ForeignKey(StockInventory, on_delete=models.CASCADE,related_name='purchase_return_items')
    qty = models.PositiveIntegerField()
    sub_total=models.DecimalField(max_digits=14,decimal_places=2,default=0,help_text="Auto calculated field. Do not fill.")

    def save(self,*args,**kwargs):
        self.sub_total=self.stock_item.buying_price*self.quantity
        super().save(*args,**kwargs)

    class Meta:
        ordering = ['-id']
        verbose_name_plural = "Purchase Return Items"
        indexes = [
            models.Index(fields=['return_record'], name='idx_purchase_returned_record'),
            models.Index(fields=['stock_item'], name='idx_purchase_returned_stock'),
        ]

    def __str__(self):
        return f"{self.return_record.original_purchase.purchase_id} Qty({self.quantity})"
