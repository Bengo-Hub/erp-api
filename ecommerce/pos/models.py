from django.db import models
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal
from ecommerce.product.models import *
from crm.contacts.models import Contact
from ecommerce.stockinventory.models import StockInventory
from business.models import Branch, Bussiness, TaxRates
from addresses.models import AddressBook
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
User = get_user_model()

class Register(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='registers', blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='registers', blank=True, null=True)
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    is_open = models.BooleanField(default=False)  # Changed default to False
    opened_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='opened_registers', null=True, blank=True)
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='closed_registers', null=True, blank=True)
    cash_at_opening = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    cash_at_closing = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    total_sales = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_expenses = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.closed_at and not self.total_sales:
            self.calculate_totals()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name_plural='Cash Register'
        indexes = [
            models.Index(fields=['branch'], name='idx_register_branch'),
            models.Index(fields=['user'], name='idx_register_user'),
            models.Index(fields=['is_open'], name='idx_register_is_open'),
            models.Index(fields=['opened_at'], name='idx_register_opened_at'),
            models.Index(fields=['closed_at'], name='idx_register_closed_at'),
            models.Index(fields=['opened_by'], name='idx_register_opened_by'),
            models.Index(fields=['closed_by'], name='idx_register_closed_by'),
        ]

    def calculate_totals(self):
        # Calculate total sales
        self.total_sales = sum(sale.grand_total for sale in self.sales.filter(Q(sale_source='pos') & Q(date_added__gte=self.opened_at) & Q(date_added__lte=self.closed_at)))
        # Calculate total expenses
        self.total_expenses = sum(expense.total_amount for expense in self.expenses.filter(Q(date_added__gte=self.opened_at) & Q(date_added__lte=self.closed_at)))

    def __str__(self):
        return f"Register({self.opened_at} - {self.closed_at if not self.is_open else timezone.now().date()}) - {'Open' if self.is_open else 'Closed'}"

    def open_register(self, user, opening_balance=0, notes=None):
        """Open the register for a user"""
        if self.is_open:
            raise ValueError("Register is already open")
        
        self.is_open = True
        self.opened_by = user
        self.opened_at = timezone.now()
        self.cash_at_opening = opening_balance
        if notes:
            self.notes = notes
        self.save()
        return self

    def close_register(self, user, closing_balance=0, notes=None):
        """Close the register for a user"""
        if not self.is_open:
            raise ValueError("Register is already closed")
        
        self.is_open = False
        self.closed_by = user
        self.closed_at = timezone.now()
        self.cash_at_closing = closing_balance
        if notes:
            self.notes = notes
        self.calculate_totals()
        self.save()
        return self

    def get_current_balance(self):
        """Get current cash balance in the register"""
        if not self.is_open:
            return self.cash_at_closing or 0
        
        # Calculate current balance based on opening balance and sales
        sales_total = self.sales.filter(
            sale_source='pos',
            date_added__gte=self.opened_at,
            payment_status='Paid'
        ).aggregate(total=models.Sum('grand_total'))['total'] or 0
        
        return self.cash_at_opening + sales_total

    def get_sales_count(self):
        """Get count of sales since register was opened"""
        if not self.is_open:
            return 0
        
        return self.sales.filter(
            sale_source='pos',
            date_added__gte=self.opened_at
        ).count()

    def get_total_sales_amount(self):
        """Get total sales amount since register was opened"""
        if not self.is_open:
            return 0
        
        return self.sales.filter(
            sale_source='pos',
            date_added__gte=self.opened_at
        ).aggregate(total=models.Sum('grand_total'))['total'] or 0
    
class Sales(models.Model):
    register = models.ForeignKey(Register, on_delete=models.CASCADE, related_name='sales', blank=True, null=True)
    customer=models.ForeignKey(Contact,on_delete=models.SET_NULL, related_name="sales", blank=True, null=True)
    attendant = models.ForeignKey(User,on_delete=models.SET_NULL, related_name="sales", blank=True, null=True)
    pay_term=models.ForeignKey("PayTerm",on_delete=models.SET_NULL,related_name='sales',null=True,blank=True)
    sale_id = models.CharField(max_length=100, blank=True, null=True)
    sale_tax = models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    sale_discount=models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    sub_total = models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    additional_expenses=models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    grand_total = models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    amount_paid = models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    balance_due = models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    balance_overdue=models.DecimalField(max_digits=14,decimal_places=2, default=0.00)
    date_added = models.DateTimeField(default=timezone.now())
    date_updated = models.DateTimeField(default=timezone.now())
    status = models.CharField(max_length=20, choices=[("Draft","Draft"),("Quotation","Quotation"),("Final","Final")],default="Final", blank=True, null=True)
    payment_status = models.CharField(max_length=20, choices=[("Pending","Pending"),("Due","Due"),("Partial","Partial"),("Paid","Paid")],default="Pending", blank=True, null=True)
    paymethod = models.CharField(max_length=20,choices=(("Cash","Cash"),("Mpesa","Mpesa"),("Card","Card"),("Bank","Bank"),("Advance","Advance"),("Other","Other")), default="Cash", blank=True, null=True)
    sale_source=models.CharField(max_length=50,choices=[("pos","POS"),("online","Online"),("other","Other")],default='pos')
    delete_status=models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        
    def __str__(self):
        return self.sale_id

    class Meta:
        db_table = 'sales'
        managed = True
        verbose_name = 'Sales'
        verbose_name_plural = 'Sales'
        indexes = [
            models.Index(fields=['register'], name='idx_sales_register'),
            models.Index(fields=['customer'], name='idx_sales_customer'),
            models.Index(fields=['attendant'], name='idx_sales_attendant'),
            models.Index(fields=['sale_id'], name='idx_sales_sale_id'),
            models.Index(fields=['status'], name='idx_sales_status'),
            models.Index(fields=['payment_status'], name='idx_sales_payment_status'),
            models.Index(fields=['paymethod'], name='idx_sales_paymethod'),
            models.Index(fields=['sale_source'], name='idx_sales_source'),
            models.Index(fields=['date_added'], name='idx_sales_date_added'),
            models.Index(fields=['delete_status'], name='idx_sales_delete_status'),
        ]

class salesItems(models.Model):
    sale = models.ForeignKey(
        Sales, on_delete=models.CASCADE, related_name='salesitems')
    stock_item = models.ForeignKey(StockInventory,verbose_name="sale item",on_delete=models.CASCADE,related_name='salesitems')
    qty = models.PositiveIntegerField(default=0)
    tax_amount=models.DecimalField(max_digits=14,decimal_places=2,default=0)
    discount_amount=models.DecimalField(max_digits=14,decimal_places=2,default=0)
    unit_price=models.DecimalField(max_digits=14,decimal_places=2,default=0)
    sub_total=models.DecimalField(max_digits=14,decimal_places=2,default=0)   

    def save(self,*args,**kwargs):
        self.sub_total=self.unit_price*self.qty
        super().save(*args,**kwargs)

    def __str__(self):
        return f"{self.sale.sale_id} - {self.stock_item.product.title} {self.stock_item.variation if self.stock_item.variation else ''}"

    class Meta:
        db_table = 'salesitems'
        managed = True
        verbose_name = 'Sales Items'
        verbose_name_plural = 'Sales Items'
        indexes = [
            models.Index(fields=['sale'], name='idx_sales_items_sale'),
            models.Index(fields=['stock_item'], name='idx_sales_items_stock'),
        ]

class CustomerReward(models.Model):
    sale=models.ForeignKey(Sales,on_delete=models.CASCADE,related_name='rewards',blank=True,null=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    description = models.TextField(blank=True, null=True)
    date_created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sale.customer} - {self.amount}"

    class Meta:
        verbose_name = _("Customer Reward")
        verbose_name_plural = _("Customer Rewards")
        indexes = [
            models.Index(fields=['sale'], name='idx_customer_reward_sale'),
            models.Index(fields=['date_created'], name='idx_customer_reward_created'),
        ]

class SalesReturn(models.Model):
    return_id = models.CharField(max_length=100, blank=True, null=True)
    original_sale = models.ForeignKey(Sales, on_delete=models.CASCADE, related_name='sales_returns')
    attendant = models.ForeignKey(User,on_delete=models.SET_NULL, related_name="returns", blank=True, null=True)
    reason = models.TextField(blank=True,null=True)
    date_returned = models.DateTimeField(auto_now_add=True)
    return_amount=models.DecimalField(max_digits=14,decimal_places=2,default=0)
    return_amount_due=models.DecimalField(max_digits=14,decimal_places=2,default=0)
    payment_status = models.CharField(max_length=20, choices=[("Pending","Pending"),("Due","Due"),("Partial","Partial"),("Paid","Paid")],default="Pending", blank=True, null=True)

    class Meta:
        ordering = ['-id']
        verbose_name_plural = "Sale Returns"
        indexes = [
            models.Index(fields=['return_id'], name='idx_sales_return_id'),
            models.Index(fields=['original_sale'], name='idx_sales_return_original_sale'),
            models.Index(fields=['attendant'], name='idx_sales_return_attendant'),
            models.Index(fields=['date_returned'], name='idx_sales_return_date'),
            models.Index(fields=['payment_status'], name='idx_sales_return_pay_status'),
        ]

    def __str__(self):
        return f"Sale ID:{self.original_sale.sale_id} Date:{self.date_returned}"

class ReturnedItem(models.Model):
    return_record = models.ForeignKey(SalesReturn, on_delete=models.CASCADE,related_name='return_items')
    stock_item = models.ForeignKey(StockInventory, on_delete=models.CASCADE,related_name='return_items')
    qty = models.PositiveIntegerField()
    sub_total=models.DecimalField(max_digits=14,decimal_places=2,default=0)

    def save(self,*args,**kwargs):
        self.sub_total=self.stock_item.buying_price*self.qty
        super().save(*args,**kwargs)

    class Meta:
        ordering = ['-id']
        verbose_name_plural = "Sale Return Items"
        indexes = [
            models.Index(fields=['return_record'], name='idx_returned_item_record'),
            models.Index(fields=['stock_item'], name='idx_returned_item_stock'),
        ]

    def __str__(self):
        return f"{self.return_record.original_sale.sale_id} Qty({self.qty})"

class PayTerm(models.Model):
    duration=models.IntegerField(default=1)
    period=models.CharField(max_length=255,choices=[("Days","Days"),("Months","Months"),("Years","Years")])

    class Meta:
        ordering = ['duration']
        db_table = "sale_pay_terms"
        managed = True
        verbose_name_plural = "Sale Pay Terms"
        indexes = [
            models.Index(fields=['duration'], name='idx_pay_term_duration'),
            models.Index(fields=['period'], name='idx_pay_term_period'),
        ]

    def __str__(self):
        return f"Payment due in {self.duration} {self.period}"

class Shipping(models.Model):
    SHIPPING_STATUS_CHOICES=[
        ("pending","Pending"),
        ("confirmed","Confirmed"),
        ("shipped","Shipped"),
        ("deliverd","Delivered"),
        ("cancelled","Cancelled"),
    ]
    sale=models.ForeignKey(Sales,on_delete=models.CASCADE,related_name='shippings')
    shipping_address=models.ForeignKey(AddressBook,on_delete=models.CASCADE,related_name="shippings")
    shipping_note=models.CharField(max_length=500)
    status=models.CharField(max_length=50,choices=SHIPPING_STATUS_CHOICES,default='Pending')
    delivered_to=models.CharField(max_length=100)
    delivered_by=models.ForeignKey(User,on_delete=models.CASCADE,related_name="shipping_staff")
    created_at=models.DateTimeField(auto_now_add=True,blank=True,null=True)

    class Meta:
        ordering = ['-created_at']
        db_table = "shipping"
        managed = True
        verbose_name_plural = "Shipping"
        indexes = [
            models.Index(fields=['sale'], name='idx_shipping_sale'),
            models.Index(fields=['shipping_address'], name='idx_shipping_address'),
            models.Index(fields=['status'], name='idx_shipping_status'),
            models.Index(fields=['delivered_by'], name='idx_shipping_delivered_by'),
            models.Index(fields=['created_at'], name='idx_shipping_created_at'),
        ]

    def __str__(self):
        return self.shipping_address.address_label
    
class ShippingDocuments(models.Model):
    shipping=models.ForeignKey(Shipping,on_delete=models.CASCADE,related_name="shipping_documents")
    document=models.FileField(upload_to='shipping/files')

    class Meta:                 
        db_table = "shipping_documents"
        managed = True
        verbose_name_plural = "Shipping Documents"
        indexes = [
            models.Index(fields=['shipping'], name='idx_shipping_docs_shipping'),
        ]

    def __str__(self):
        return self.document.name if self.document else 'no file found!'       

class SalesLogs(models.Model):
    shipping=models.ForeignKey(Shipping,on_delete=models.CASCADE,related_name="shipping_tasks")
    log_date=models.DateTimeField(auto_now_add=True)
    action=models.CharField(max_length=500)
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name="shipping_tasks")
    description=models.CharField(max_length=500)

    class Meta:
        ordering = ['-log_date']
        managed = True
        verbose_name_plural = "Sales Logs"
        indexes = [
            models.Index(fields=['shipping'], name='idx_sales_logs_shipping'),
            models.Index(fields=['log_date'], name='idx_sales_logs_log_date'),
            models.Index(fields=['user'], name='idx_sales_logs_user'),
        ]

    def __str__(self):
        return self.shipping.shipping_address 

class MpesaTransaction(models.Model):
    clientName = models.CharField(max_length=255)
    clientId = models.CharField(max_length=255)
    transactionType = models.CharField(max_length=20,choices=(("deposit","deposit"),("withdrawal","withdrawal")),default="withdrawal")
    transactionRef = models.CharField(max_length=255)
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.transactionRef

    class Meta:
        db_table = 'mpesa_transactions'
        managed = True
        verbose_name = 'Mpesa Transactions'
        verbose_name_plural = 'Mpesa Transactions'
        indexes = [
            models.Index(fields=['clientId'], name='idx_mpesa_transaction_client'),
            models.Index(fields=['transactionType'], name='idx_mpesa_transaction_type'),
            models.Index(fields=['transactionRef'], name='idx_mpesa_transaction_ref'),
            models.Index(fields=['date'], name='idx_mpesa_transaction_date'),
        ]

class SuspendedSale(models.Model):
    reference_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True)
    attendant = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    items = models.JSONField()  # Store cart items
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Suspended Sale {self.reference_number}"


class POSAdvanceSaleRecord(models.Model):
    """
    This model serves as a connector between POS Sales and Payroll Advances.
    It doesn't duplicate the Advances model but links sales to existing advances.
    """
    sale = models.OneToOneField(
        Sales, 
        on_delete=models.CASCADE, 
        related_name='staff_advance_record'
    )
    advance = models.ForeignKey(
        'payroll.Advances',
        on_delete=models.CASCADE,
        related_name='pos_sales',
        null=True
    )
    reference_id = models.CharField(max_length=100, unique=True)
    date_created = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    
    class Meta:
        ordering = ['-date_created']
        verbose_name = 'POS Advance Sale Record'
        verbose_name_plural = 'POS Advance Sale Records'
        db_table = 'pos_advance_sale_records'
        indexes = [
            models.Index(fields=['sale'], name='idx_pos_advance_sale'),
            models.Index(fields=['advance'], name='idx_pos_advance_advance'),
            models.Index(fields=['reference_id'], name='idx_pos_advance_ref'),
            models.Index(fields=['date_created'], name='idx_pos_advance_date'),
            models.Index(fields=['created_by'], name='idx_pos_advance_created_by'),
        ]
    
    def __str__(self):
        return f"POS Sale: {self.reference_id}"