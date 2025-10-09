from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import CartSession

User = get_user_model()

class Coupon(models.Model):
    """Coupon model for cart-wide discounts during checkout"""
    DISCOUNT_TYPES = [
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
        ('free_shipping', 'Free Shipping'),
    ]
    
    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPES)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    minimum_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    max_uses = models.PositiveIntegerField(default=0, help_text="0 means unlimited")
    current_uses = models.PositiveIntegerField(default=0)
    is_single_use = models.BooleanField(default=False, help_text="Can be used only once per user")
    description = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.code} ({self.get_discount_type_display()})"
    
    def is_valid_for_use(self):
        """Basic validity check for listing available coupons"""
        now = timezone.now()
        
        # Check basic validity - is it active and within valid date range?
        if not self.is_active:
            return False
        
        if self.start_date and self.start_date > now:
            return False
        
        if self.end_date and self.end_date < now:
            return False
        
        # Check usage limits - has it reached its maximum use count?
        if self.max_uses > 0 and self.current_uses >= self.max_uses:
            return False
            
        return True
        
    def is_valid(self, cart_total=None, user=None):
        """Check if the coupon is valid based on various conditions"""
        now = timezone.now()
        
        # Check basic validity
        if not self.is_active:
            return False, "This coupon is no longer active"
        
        # Check date validity
        if self.start_date and self.start_date > now:
            return False, "This coupon is not yet active"
        
        if self.end_date and self.end_date < now:
            return False, "This coupon has expired"
        
        # Check usage limits
        if self.max_uses > 0 and self.current_uses >= self.max_uses:
            return False, "This coupon has reached its usage limit"
        
        # Check minimum order amount
        if cart_total is not None and cart_total < self.minimum_order_amount:
            return False, f"You need to spend at least {self.minimum_order_amount} to use this coupon"
        
        # Check if user already used a single-use coupon
        if user and self.is_single_use:
            if CouponUsage.objects.filter(coupon=self, user=user).exists():
                return False, "You have already used this coupon"
                
        return True, "Coupon is valid"
    
    def calculate_discount(self, cart_total, shipping_fee=0):
        """Calculate the discount amount based on coupon type and cart total"""
        if self.discount_type == 'percentage':
            return (cart_total * self.discount_value) / 100
        elif self.discount_type == 'fixed':
            return min(self.discount_value, cart_total)  # Don't discount more than the cart total
        elif self.discount_type == 'free_shipping':
            return shipping_fee
        return 0
    
    def apply_to_cart(self, cart, user=None):
        """Apply this coupon to a cart"""
        cart_total = cart.get_subtotal()
        is_valid, message = self.is_valid(cart_total, user)
        
        if not is_valid:
            return False, message
        
        shipping_fee = 0  # In a real implementation, get this from the cart
        discount_amount = self.calculate_discount(cart_total, shipping_fee)
        
        # Create a cart coupon record
        cart_coupon, created = CartCoupon.objects.get_or_create(
            cart=cart,
            defaults={
                'coupon': self,
                'discount_amount': discount_amount,
            }
        )
        
        if not created:
            cart_coupon.coupon = self
            cart_coupon.discount_amount = discount_amount
            cart_coupon.save()
        
        # Record usage if user is authenticated
        if user and user.is_authenticated:
            CouponUsage.objects.create(
                coupon=self,
                user=user,
                discount_amount=discount_amount
            )
            
            # Update coupon usage count
            self.current_uses += 1
            self.save()
        
        return True, f"Coupon applied successfully! You saved KSh {discount_amount}"
        
    class Meta:
        db_table = 'coupons'
        verbose_name = 'Coupon'
        verbose_name_plural = 'Coupons'

class CartCoupon(models.Model):
    """Represents a coupon applied to a cart"""
    cart = models.OneToOneField(CartSession, on_delete=models.CASCADE, related_name='coupon')
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='cart_coupons')
    applied_at = models.DateTimeField(auto_now_add=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    def __str__(self):
        return f"{self.coupon.code} applied to {self.cart}"
    
    class Meta:
        db_table = 'cart_coupons'
        verbose_name = 'Cart Coupon'
        verbose_name_plural = 'Cart Coupons'

class CouponUsage(models.Model):
    """Tracks usage of coupons by users"""
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='usages')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='coupon_usages')
    used_at = models.DateTimeField(auto_now_add=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    def __str__(self):
        return f"{self.coupon.code} used by {self.user.username}"
    
    class Meta:
        db_table = 'coupon_usages'
        verbose_name = 'Coupon Usage'
        verbose_name_plural = 'Coupon Usages'
        unique_together = ('coupon', 'user')  # Each user can use a coupon only once
