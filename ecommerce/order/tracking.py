"""
Order tracking service for customers to track their orders.
Provides functionality for tracking orders and sending status updates to customers.
"""
import logging
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from .models import Order

logger = logging.getLogger(__name__)

class OrderTrackingService:
    """
    Service for tracking orders and generating tracking information for customers.
    This service consolidates the tracking status and presents it in a customer-friendly format.
    """
    
    STATUS_DESCRIPTIONS = {
        "pending": "Your order has been received and is awaiting confirmation.",
        "confirmed": "Your order has been confirmed and is being prepared.",
        "processing": "Your order is currently being processed in our system.",
        "fulfilled": "All items in your order have been fulfilled and will be packed shortly.",
        "packed": "Your order has been packed and is waiting for shipping.",
        "shipped": "Your order has been shipped and is on its way to you.",
        "in_transit": "Your order is in transit to your delivery address.",
        "out_for_delivery": "Your order is out for delivery and will arrive today.",
        "delivered": "Your order has been delivered to your destination.",
        "complete": "Your order has been completed successfully. Thank you for your business!",
        "cancelled": "Your order has been cancelled.",
        "on_hold": "Your order is currently on hold. Customer service will contact you.",
        "backordered": "Some items in your order are backordered and will be shipped when available.",
        "refund_requested": "A refund has been requested for your order.",
        "refunded": "Your order has been refunded.",
        "payment_failed": "There was an issue with your payment. Please update your payment information."
    }
    
    CUSTOMER_STATUS_MAPPING = {
        # Map internal statuses to customer-friendly statuses
        "pending": "Order Received",
        "confirmed": "Order Confirmed",
        "processing": "Processing",
        "fulfilled": "Fulfilled",
        "packed": "Packed",
        "shipped": "Shipped",
        "in_transit": "In Transit",
        "out_for_delivery": "Out for Delivery",
        "delivered": "Delivered",
        "complete": "Completed",
        "cancelled": "Cancelled",
        "on_hold": "On Hold",
        "backordered": "Backordered",
        "refund_requested": "Refund Requested",
        "refunded": "Refunded",
        "payment_failed": "Payment Failed"
    }
    
    def __init__(self, order_id=None, order=None):
        """Initialize with either an order or order_id"""
        if order:
            self.order = order
        elif order_id:
            try:
                self.order = Order.objects.get(order_id=order_id)
            except Order.DoesNotExist:
                raise ValueError(f"Order with ID {order_id} not found")
        else:
            raise ValueError("Either order or order_id must be provided")
    
    def get_tracking_info(self):
        """
        Get comprehensive tracking information for the order
        Returns a dictionary with tracking details
        """
        # Use centralized timestamps and events; legacy OrderHistory removed
        history = []
        
        # Get shipping info if available
        shipping_info = {
            "tracking_number": self.order.tracking_number,
            "shipping_provider": self.order.shipping_provider,
            "shipping_address": self.format_address(self.order.shipping_address) if self.order.shipping_address else None,
        }
        
        # Calculate estimated delivery date if the order is shipped but not delivered
        estimated_delivery = None
        if self.order.status in ['shipped', 'in_transit'] and not getattr(self.order, 'estimated_delivery_date', None):
            # Default to 3 days from shipped_at if available
            ship_dt = getattr(self.order, 'shipped_at', None)
            if ship_dt:
                estimated_delivery = ship_dt + timezone.timedelta(days=3)
        else:
            estimated_delivery = getattr(self.order, 'estimated_delivery_date', None)
            
        # Format history events for customer view
        timeline = []
        # Compose a minimal timeline from centralized lifecycle timestamps
        lifecycle = [
            ('pending', getattr(self.order, 'order_date', None)),
            ('confirmed', getattr(self.order, 'confirmed_at', None)),
            ('processing', getattr(self.order, 'processing_at', None)),
            ('packed', getattr(self.order, 'packed_at', None)),
            ('shipped', getattr(self.order, 'shipped_at', None)),
            ('delivered', getattr(self.order, 'delivered_at', None)),
            ('cancelled', getattr(self.order, 'cancelled_at', None)),
        ]
        for status_key, ts in lifecycle:
            if ts:
                timeline.append({
                    "status": self.CUSTOMER_STATUS_MAPPING.get(status_key, status_key),
                    "description": self.STATUS_DESCRIPTIONS.get(status_key, ""),
                    "timestamp": ts,
                })
        
        return {
            "order_id": self.order.order_id,
            "current_status": self.CUSTOMER_STATUS_MAPPING.get(self.order.status, self.order.status),
            "status_description": self.STATUS_DESCRIPTIONS.get(self.order.status, ""),
            "payment_status": self.order.payment_status,
            "order_date": getattr(self.order, 'order_date', None) or getattr(self.order, 'created_at', None),
            "estimated_delivery": estimated_delivery,
            "shipping_info": shipping_info,
            "timeline": timeline,
            "items": self.get_order_items(),
            "can_cancel": self.can_cancel_order(),
            "track_url": self.get_tracking_url(),
        }
    
    def get_order_items(self):
        """Get formatted order items with status information"""
        items = []
        items_manager = getattr(self.order, 'items', None)
        try:
            iterable = items_manager.all() if items_manager is not None else []
        except Exception:
            iterable = []
        for item in iterable:
            item_status = "Preparing"
            if self.order.status in ['shipped', 'in_transit', 'out_for_delivery', 'delivered', 'complete']:
                item_status = "Shipped"
            elif self.order.status in ['backordered']:
                item_status = "Backordered"
            elif self.order.status in ['cancelled']:
                item_status = "Cancelled"
                
            items.append({
                "id": item.id,
                "product_name": getattr(item, 'name', None) or item.sku or "Product",
                "variant": None,
                "quantity": item.quantity,
                "price": getattr(item, 'unit_price', 0),
                "total": getattr(item, 'total_price', 0),
                "status": item_status,
                "image_url": None,
            })
        return items
    
    def format_address(self, address):
        """Format address for display"""
        if not address:
            return None
            
        return {
            "name": address.contact_name,
            "street": address.address_line1,
            "street2": address.address_line2,
            "city": address.city,
            "state": address.state,
            "postal_code": address.postal_code,
            "country": address.country,
            "phone": address.phone,
        }
    
    def get_event_description(self, event):
        """Get a customer-friendly description for the event"""
        # Use the message from the event if it's customer-appropriate, otherwise use defaults
        if "status changed" in event.message.lower():
            return self.STATUS_DESCRIPTIONS.get(event.status, event.message)
        return event.message
    
    def can_cancel_order(self):
        """Check if the order can be cancelled by the customer"""
        cancellable_statuses = ['pending', 'confirmed']
        return self.order.status in cancellable_statuses
    
    def get_tracking_url(self):
        """Generate tracking URL for the carrier if available"""
        if not getattr(self.order, 'tracking_number', None) or not getattr(self.order, 'shipping_provider', None):
            return None
            
        # Common carrier tracking URL formats
        tracking_urls = {
            'dhl': f"https://www.dhl.com/en/express/tracking.html?AWB={self.order.tracking_number}",
            'fedex': f"https://www.fedex.com/apps/fedextrack/?tracknumbers={self.order.tracking_number}",
            'ups': f"https://www.ups.com/track?tracknum={self.order.tracking_number}",
            'usps': f"https://tools.usps.com/go/TrackConfirmAction?tLabels={self.order.tracking_number}",
            'kenya_post': f"https://www.posta.co.ke/track-trace/?track_number={self.order.tracking_number}",
            'g4s': f"https://www.g4s.com/en-ke/tracking?tracking_number={self.order.tracking_number}",
            'wells_fargo': f"https://www.wellsfargo.co.ke/tracking?tracking_number={self.order.tracking_number}",
        }
        
        provider = (self.order.shipping_provider or '').lower().replace(' ', '_')
        return tracking_urls.get(provider)
    
    @transaction.atomic
    def send_tracking_update(self, notification_type=None):
        """
        Send tracking update to the customer via preferred notification channel
        notification_type options: 'status_update', 'shipping_update', 'delivery_update'
        """
        if not notification_type:
            notification_type = 'status_update'
            
        if not self.order.customer or not self.order.customer.user:
            logger.warning(f"Cannot send tracking update for order {self.order.order_id}: No customer found")
            return False
            
        # Map notification type to valid order event types
        event_type_mapping = {
            'status_update': self.order.status,  # Use the current order status
            'shipping_update': 'order_shipped',
            'delivery_update': 'order_delivered'
        }
        
        event_type = event_type_mapping.get(notification_type, 'order_confirmed')
        
        # Use centralized notification system; no legacy fallback
        try:
            from integrations.utils_api import send_order_notification as central_notification
            result = central_notification(
                order=self.order,
                event_type=event_type,
                channels=['email', 'sms', 'in_app']
            )
            success = result.get('success', False)
        except Exception as e:
            logger.warning(f"Centralized notification service unavailable: {str(e)}")
            success = False
        
        return success
