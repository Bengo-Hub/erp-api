from django.db import models
from django.utils import timezone
from ecommerce.stockinventory.models import StockInventory
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from business.models import Branch
import uuid

User = get_user_model()

class CartSession(models.Model):
    """Represents a shopping cart session, which can belong to a user or a guest"""
    session_key = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cart_sessions', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    converted_to_order = models.ForeignKey('core_orders.BaseOrder', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_cart')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='carts')
    
    def __str__(self):
        if self.user:
            return f"Cart for {self.user.username} ({self.session_key})"
        return f"Guest Cart ({self.session_key})"
    
    def save(self, *args, **kwargs):
        # Set expiration to 30 days from now if not set
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(days=30)
        super().save(*args, **kwargs)
    
    def get_total_items(self):
        return sum(item.quantity for item in self.items.all())
    
    def get_subtotal(self):
        return sum(item.item_subtotal for item in self.items.all())
    
    def get_total_tax(self):
        return sum(item.tax_amount for item in self.items.all())
    
    def get_total(self):
        return sum(item.item_total for item in self.items.all())
    
    def get_discount_amount(self):
        """Get total discount amount for the cart"""
        return sum(item.discount_amount for item in self.items.all())
    
    def clear(self):
        self.items.all().delete()
        
    def merge_with(self, other_cart):
        """Merge items from another cart into this cart"""
        for item in other_cart.items.all():
            # Check if this cart already has the same item
            existing_item = self.items.filter(stock_item=item.stock_item).first()
            
            if existing_item:
                # Update quantity of existing item
                existing_item.quantity += item.quantity
                existing_item.save()
            else:
                # Create new item in this cart
                CartItem.objects.create(
                    cart=self,
                    stock_item=item.stock_item,
                    quantity=item.quantity,
                    selling_price=item.stock_item.selling_price
                )
        # Clear the other cart after merging
        other_cart.clear()
        
    def convert_to_order(self, order):
        """Mark cart as converted to order"""
        self.converted_to_order = order
        self.is_active = False
        self.save()
        
    class Meta:
        db_table = 'cart_sessions'
        managed = True
        verbose_name = 'Cart Session'
        verbose_name_plural = 'Cart Sessions'
        indexes = [
            models.Index(fields=['session_key'], name='idx_cart_session_key'),
            models.Index(fields=['user'], name='idx_cart_session_user'),
            models.Index(fields=['is_active'], name='idx_cart_session_active'),
            models.Index(fields=['created_at'], name='idx_cart_session_created_at'),
            models.Index(fields=['expires_at'], name='idx_cart_session_expires_at'),
        ]


class CartItem(models.Model):
    """Represents an item in a shopping cart"""
    cart = models.ForeignKey(CartSession, on_delete=models.CASCADE, related_name='items')
    stock_item = models.ForeignKey(StockInventory, on_delete=models.CASCADE, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price at time of adding to cart")
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    item_subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    item_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        # Calculate item totals when saving
        self.item_subtotal = self.selling_price * self.quantity
        self.item_total = self.item_subtotal + self.tax_amount - self.discount_amount
        
        # Update cart session timestamp
        self.cart.updated_at = timezone.now()
        self.cart.save()
        
        super().save(*args, **kwargs)
    
    def get_subtotal(self):
        """Get subtotal for this item"""
        return self.selling_price * self.quantity
    
    def get_tax_amount(self):
        """Get tax amount for this item"""
        return self.tax_amount
    
    def get_item_total(self):
        """Get total for this item including tax and discounts"""
        return self.item_total
    
    def __str__(self):
        return f"{self.stock_item.product.title} x {self.quantity} in {self.cart}"
    
    class Meta:
        db_table = 'cart_items'
        managed = True
        verbose_name = 'Cart Item'
        verbose_name_plural = 'Cart Items'
        indexes = [
            models.Index(fields=['cart'], name='idx_cart_item_cart'),
            models.Index(fields=['stock_item'], name='idx_cart_item_stock'),
            models.Index(fields=['added_at'], name='idx_cart_item_added_at'),
        ]


class SavedForLater(models.Model):
    """Items saved for later purchase"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_items')
    stock_item = models.ForeignKey(StockInventory, on_delete=models.CASCADE, related_name='saved_items')
    saved_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.stock_item.product.title} saved by {self.user.username}"
    
    class Meta:
        db_table = 'saved_for_later'
        managed = True
        verbose_name = 'Saved Item'
        verbose_name_plural = 'Saved Items'
        #unique_together = ('user', 'stock_item')
        indexes = [
            models.Index(fields=['user'], name='idx_saved_for_later_user'),
            models.Index(fields=['stock_item'], name='idx_saved_for_later_stock'),
            models.Index(fields=['saved_at'], name='idx_saved_for_later_saved_at'),
        ]


@receiver(post_save, sender=User)
def create_cart_for_new_user(sender, instance, created, **kwargs):
    """Create a cart session for newly registered users"""
    if created:
        CartSession.objects.create(
            user=instance,
            session_key=f"user-{instance.id}-{uuid.uuid4().hex[:8]}",
        )
