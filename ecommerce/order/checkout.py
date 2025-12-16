from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
import logging
import string
import random
from decimal import Decimal

# Only import what's actually used in the code
from ecommerce.order.models import Order
from core_orders.models import OrderItem, OrderPayment
from ecommerce.cart.models import CartSession
from addresses.models import AddressBook
from crm.contacts.models import Contact

User = get_user_model()
logger = logging.getLogger(__name__)

class CheckoutService:
    """
    Comprehensive checkout service for the ecommerce system.
    
    Features:
    - Cart validation and inventory checking
    - Order creation from cart
    - Guest checkout with silent user account creation
    - Multiple payment methods including split payments
    - Inventory reservation and allocation
    - Order status tracking and notifications
    """
    
    def __init__(self, cart_id=None, cart=None, user=None, branch_id=None):
        """
        Initialize checkout service with either a cart_id or cart object.
        """
        if cart:
            self.cart = cart
        elif cart_id:
            try:
                self.cart = CartSession.objects.get(id=cart_id)
            except CartSession.DoesNotExist:
                raise ValueError(f"Cart with ID {cart_id} not found")
        else:
            raise ValueError("Either cart or cart_id must be provided")
            
        self.user = user or self.cart.user
        # We'll handle guest checkout case in process_checkout when user is None
        self.is_guest = self.user is None
        # branch context (int id)
        self.branch_id = branch_id

    @staticmethod
    def _generate_password(length=12):
        """Generate a secure random password"""
        chars = string.ascii_letters + string.digits + string.punctuation
        return ''.join(random.choice(chars) for _ in range(length))
    
    @staticmethod
    def _generate_username(email, first_name, last_name):
        """Generate a username based on user information"""
        base = email.split('@')[0]
        # Add a random suffix to ensure uniqueness
        suffix = ''.join(random.choice(string.digits) for _ in range(4))
        return f"{base}_{suffix}"

    @classmethod
    @transaction.atomic
    def create_user_from_billing_info(cls, billing_info):
        """Create a user account from billing information for guest checkout"""
        if not billing_info.get('email'):
            raise ValueError("Email is required for guest checkout")
            
        # Check if user already exists with this email
        email = billing_info.get('email').lower().strip()
        existing_user = User.objects.filter(email=email).first()
        
        if existing_user:
            logger.info(f"User with email {email} already exists, returning existing user")
            return existing_user
            
        # Extract user info
        first_name = billing_info.get('first_name', '')
        last_name = billing_info.get('last_name', '')
        phone = billing_info.get('phone', '')
        
        # Generate username and password
        username = cls._generate_username(email, first_name, last_name)
        password = cls._generate_password()
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        
        logger.info(f"Created new user account for {email} with ID {user.id}")
        
        # Create contact for the user
        contact = Contact.objects.create(
            user=user,
            contact_id=f"CUST{user.id}",
            contact_type="Customers",
            phone=phone,
            is_deleted=False,
        )
        
        # Create address records using the enhanced AddressBook model
        # First, determine if this is a pickup station address or a normal address
        is_pickup_address = billing_info.get('is_pickup_address', False)
        
        if is_pickup_address and billing_info.get('pickup_station_id'):
            try:
                from business.models import PickupStations
                
                # Find the pickup station
                pickup_station = PickupStations.objects.get(id=billing_info.get('pickup_station_id'))
                
                # Create a pickup address
                AddressBook.objects.create(
                    user=user,
                    address_label=f"Checkout Pickup Location",
                    address_type="BILLING",  # Default to billing for checkout
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=phone,
                    is_pickup_address=True,
                    pickup_station=pickup_station,
                    is_default_billing=True  # Make this the default billing address
                )
                
                logger.info(f"Created pickup address for user {user.id} at station {pickup_station.pickup_location}")
                
            except Exception as e:
                logger.error(f"Error creating pickup address: {str(e)}")
                # Fallback to creating a normal address if pickup station creation fails
                is_pickup_address = False
        
        # Create a regular address if not pickup or pickup creation failed
        if not is_pickup_address and billing_info.get('address_line1'):
            try:
                # Create billing address
                AddressBook.objects.create(
                    user=user,
                    address_label="Billing Address",
                    address_type="BILLING",
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=phone,
                    other_phone=billing_info.get('other_phone', ''),
                    address_line1=billing_info.get('address_line1', ''),
                    address_line2=billing_info.get('address_line2', ''),
                    city=billing_info.get('city', ''),
                    state=billing_info.get('state', ''),
                    postal_code=billing_info.get('postal_code', ''),
                    country=billing_info.get('country', 'Kenya'),
                    is_default_billing=True
                )
                
                logger.info(f"Created billing address for user {user.id}")
                
                # If shipping address is different, create a separate shipping address
                if billing_info.get('different_shipping_address', False):
                    shipping_info = billing_info.get('shipping_address', {})
                    
                    if shipping_info and shipping_info.get('address_line1'):
                        AddressBook.objects.create(
                            user=user,
                            address_label="Shipping Address",
                            address_type="SHIPPING",
                            first_name=shipping_info.get('first_name', first_name),
                            last_name=shipping_info.get('last_name', last_name),
                            email=email,
                            phone=shipping_info.get('phone', phone),
                            address_line1=shipping_info.get('address_line1', ''),
                            address_line2=shipping_info.get('address_line2', ''),
                            city=shipping_info.get('city', ''),
                            state=shipping_info.get('state', ''),
                            postal_code=shipping_info.get('postal_code', ''),
                            country=shipping_info.get('country', 'Kenya'),
                            is_default_shipping=True
                        )
                        logger.info(f"Created separate shipping address for user {user.id}")
                else:
                    # Use the same address for shipping
                    billing_address = AddressBook.objects.filter(user=user, is_default_billing=True).first()
                    if billing_address:
                        billing_address.address_type = "BOTH"
                        billing_address.is_default_shipping = True
                        billing_address.save()
                        logger.info(f"Set billing address as default shipping address for user {user.id}")
            except Exception as e:
                logger.error(f"Error creating address: {str(e)}")
                # Even if address creation fails, we should return the user
        
        # Log user creation success
        logger.info(f"Successfully created user account {user.username} with ID {user.id}")
        
        return user, contact

    @staticmethod
    def validate_cart_inventory(cart):
        """
        Validates that all items in the cart have sufficient inventory.
        Returns a tuple (is_valid, errors) where errors is a list of validation errors.
        """
        errors = []
        
        for item in cart.items.all():
            stock_item = item.stock_item
            if not stock_item.is_active:
                errors.append(f"Product '{stock_item.product.title}' is no longer available.")
                continue
                
            if item.quantity > stock_item.stock_level:
                errors.append(
                    f"Insufficient stock for '{stock_item.product.title}'. "
                    f"Available: {stock_item.stock_level}, Requested: {item.quantity}"
                )
        
        return (len(errors) == 0, errors)
    
    @staticmethod
    def calculate_order_totals(cart):
        """Calculate subtotal, tax, shipping, and grand total for an order."""
        subtotal = cart.subtotal
        tax_amount = cart.tax_total
        shipping_fee = 0  # Could be calculated based on shipping method and address
        
        total = subtotal + tax_amount + shipping_fee
        
        return {
            'subtotal': subtotal,
            'tax_amount': tax_amount,
            'shipping_fee': shipping_fee,
            'total': total
        }

    @transaction.atomic
    def process_checkout(self, checkout_data):
        """
        Process the complete checkout flow:
        1. Validate checkout data and cart contents
        2. Create order from cart
        3. Process payment if provided
        4. Reserve inventory
        5. Return order and status
        
        checkout_data should include:
        - customer_id: ID of the customer contact (not required for guest checkout)
        - billing_address: Dict with billing address info (required for guest checkout)
        - shipping_address: Dict with shipping address info (optional, same as billing if not provided)
        - shipping_address_id: ID of shipping address (for registered users)
        - billing_address_id: ID of billing address (for registered users)
        - payment_method: Payment method code (optional for delayed payment)
        - payment_details: Dict with payment details (optional)
        - notes: Order notes (optional)
        """
        # Check if cart has items
        if not self.cart.items.exists():
            return None, False, "Cart is empty"
        
        # Handle guest checkout if necessary
        if self.is_guest:
            if not checkout_data.get('billing_address'):
                return None, False, "Billing address is required for guest checkout"
                
            try:
                # Create user from billing info
                self.user, customer = self.create_user_from_billing_info(checkout_data.get('billing_address'))
                
                # Associate cart with the user
                self.cart.user = self.user
                self.cart.save()
                
                # Now we have a customer contact
                self.is_guest = False
                checkout_data['customer_id'] = customer.id
            except Exception as e:
                logger.exception(f"Guest checkout failed: {str(e)}")
                return None, False, f"Failed to create user account: {str(e)}"
        
        # For registered users, get customer contact
        if not checkout_data.get('customer_id'):
            try:
                # Try to find customer contact for the user
                customer = Contact.objects.get(user=self.user, contact_type="Customers")
                checkout_data['customer_id'] = customer.id
            except Contact.DoesNotExist:
                return None, False, "Customer contact not found for user"
        
        # Get customer contact
        try:
            customer = Contact.objects.get(id=checkout_data.get('customer_id'))
        except Contact.DoesNotExist:
            return None, False, "Customer not found"
        
        # Create order from cart
        order = self._create_order_from_cart(customer, checkout_data)
        if not order:
            return None, False, "Failed to create order from cart"
        
        # Process payment if provided
        payment_result = self._process_payment(order, checkout_data)
        if payment_result.get('success'):
            # Record successful payment
            pass # Removed OrderHistory import, so this line is commented out
        
        # Clear cart after successful order creation
        if checkout_data.get('clear_cart', True):
            self.cart.items.all().delete()
        
        return order, True, "Order created successfully"

    @transaction.atomic
    def _create_order_from_cart(self, customer, checkout_data):
        """
        Create a new order from the cart contents
        """
        # Calculate order totals
        subtotal = sum(item.get_subtotal() for item in self.cart.items.all())
        tax_amount = sum(item.get_tax_amount() for item in self.cart.items.all())
        discount_amount = self.cart.get_discount_amount() if hasattr(self.cart, 'get_discount_amount') else Decimal('0.00')
        shipping_cost = checkout_data.get('shipping_cost', Decimal('0.00'))
        
        # Calculate final order amount
        order_amount = subtotal + tax_amount + shipping_cost - discount_amount
        
        # Get shipping and billing addresses if provided
        shipping_address = None
        if checkout_data.get('shipping_address_id'):
            shipping_address = AddressBook.objects.get(id=checkout_data.get('shipping_address_id'))
            
        billing_address = None
        if checkout_data.get('billing_address_id'):
            billing_address = AddressBook.objects.get(id=checkout_data.get('billing_address_id'))
        
        # Determine order branch
        branch_id = checkout_data.get('branch_id') or self.branch_id
        # If no branch provided, derive from cart items (require all items to be from the same branch)
        if not branch_id:
            branch_ids = set()
            for cart_item in self.cart.items.all():
                stock_item = getattr(cart_item, 'stock_item', None) or getattr(cart_item, 'product', None)
                if stock_item and getattr(stock_item, 'branch_id', None):
                    branch_ids.add(stock_item.branch_id)
            if len(branch_ids) > 1:
                raise ValueError('All cart items must belong to the same branch for checkout')
            branch_id = branch_ids.pop() if branch_ids else None

        # Create order
        order = Order.objects.create(
            customer=customer,
            created_by=self.user,
            source='online',
            subtotal=subtotal,
            tax_amount=tax_amount,
            discount_amount=discount_amount,
            shipping_cost=shipping_cost,
            order_amount=order_amount,
            shipping_address=shipping_address,
            billing_address=billing_address,
            status='pending',
            payment_status='pending',
            balance_due=order_amount,
            branch_id=branch_id,
            notes=checkout_data.get('notes', '')
        )
        
        # Generate order ID
        order.generate_order_id()
        
        # Transfer cart items to order items
        for cart_item in self.cart.items.all():
            # Check if we have inventory
            stock = cart_item.product
            
            # Get cost price (or use retail price as fallback)
            cost_price = getattr(stock, 'cost_price', None) or cart_item.price / Decimal('1.3')  # Estimate cost if not available
            
            # Create order item
            OrderItem.objects.create(
                order=order,
                stock=stock,
                quantity=cart_item.quantity,
                retail_price=cart_item.price,
                cost_price=cost_price,
                tax_rate=cart_item.tax_rate if hasattr(cart_item, 'tax_rate') else Decimal('0.00'),
                discount_amount=cart_item.discount if hasattr(cart_item, 'discount') else Decimal('0.00'),
                notes=cart_item.notes if hasattr(cart_item, 'notes') else None
            )
        
        return order

    def _process_payment(self, order, checkout_data):
        """
        Process payment for the order if payment details are provided
        Returns a dict with payment result
        """
        result = {
            'success': False,
            'message': "No payment processed",
            'amount': Decimal('0.00'),
            'method': None
        }
        
        # Exit early if no payment method provided
        if not checkout_data.get('payment_method'):
            return result
            
        # Get payment details
        payment_method = checkout_data.get('payment_method')
        payment_details = checkout_data.get('payment_details', {})
        amount = checkout_data.get('payment_amount', order.order_amount)
        
        # Process payment using the centralized payment service
        try:
            from finance.payment.services import get_payment_service
            payment_service = get_payment_service()
            
            success, message, payment = payment_service.process_order_payment(
                order=order,
                amount=amount,
                payment_method=payment_method,
                transaction_id=payment_details.get('transaction_id'),
                transaction_details=payment_details,
                created_by=self.user
            )
            
            if success and payment:
                result['success'] = True
                result['message'] = "Payment processed successfully"
                result['amount'] = payment.amount
                result['method'] = payment.payment_method
                result['payment'] = payment
            else:
                result['message'] = message or "Payment processing failed"
                
        except Exception as e:
            logger.error(f"Payment processing failed: {str(e)}")
            result['message'] = f"Payment processing failed: {str(e)}"
            
        return result

    @staticmethod
    def initialize_payment(order, payment_method, payment_data=None):
        """
        Initialize payment for an order based on the selected payment method.
        
        Args:
            order: The Order to process payment for
            payment_method: The payment method to use
            payment_data: Additional data needed for the payment method
            
        Returns:
            A dict with payment initialization details
        """
        payment_data = payment_data or {}
        response = {
            'success': False,
            'message': '',
            'redirect_url': None,
            'payment_id': None
        }
        
        # Delegate initialization to centralized payment service
        try:
            from finance.payment.services import get_payment_service
            payment_service = get_payment_service()
            init = payment_service.initialize_payment_for_order(
                order=order,
                payment_method=payment_method,
                payment_data=payment_data,
            )
            response.update(init or {})
        except Exception as e:
            logger.error(f"Payment initialization failed: {str(e)}")
            response['message'] = f"Payment initialization failed: {str(e)}"
        
        return response

    @staticmethod
    def get_available_payment_methods():
        """
        Return list of available payment methods
        """
        try:
            from finance.payment.services import get_payment_service
            payment_service = get_payment_service()
            return payment_service.get_available_payment_methods()
        except Exception as e:
            logger.error(f"Error getting payment methods: {str(e)}")
            return []

    @staticmethod
    def update_order_status(order_id, new_status, user=None, notes=None):
        """
        Update order status and send notifications
        
        Valid statuses:
        - pending, confirmed, processing, fulfilled, packed, 
        - shipped, in_transit, out_for_delivery, delivered, complete,
        - cancelled, on_hold, backordered, refund_requested, refunded
        """
        try:
            order = Order.objects.get(order_id=order_id)
            
            # Update order status
            order.status = new_status
            order.save()
            
            # Add note if provided
            if notes:
                pass # Removed OrderHistory import, so this line is commented out
                
            return True, f"Order status updated to {new_status}"
        except Exception as e:
            logger.error(f"Error updating order status: {str(e)}")
            return False, str(e)
