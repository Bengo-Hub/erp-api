from django.shortcuts import get_object_or_404
from django.db import transaction
from django.http import Http404
import uuid

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from .models import CartSession, CartItem, SavedForLater
from .serializers import CartSessionSerializer, CartItemSerializer, SavedForLaterSerializer
from ecommerce.stockinventory.models import StockInventory
from django.contrib.auth import get_user_model
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


class CartSessionViewSet(BaseModelViewSet):
    """
    API endpoint for managing cart sessions.
    Supports guest carts (with session keys) and user carts.
    """
    serializer_class = CartSessionSerializer
    
    def get_permissions(self):
        # Allow anyone to create or access a cart with a valid session key
        if self.action in ['create', 'retrieve_by_session']:
            return [AllowAny()]
        return [IsAuthenticated()]
    
    def get_queryset(self):
        if self.request.user.is_authenticated:
            return CartSession.objects.filter(user=self.request.user, is_active=True)
        return CartSession.objects.none()
    
    def create(self, request, *args, **kwargs):
        """Create a new cart session, either for a guest or a logged-in user"""
        try:
            correlation_id = get_correlation_id(request)
            # If user is logged in, get or create their cart
            if request.user.is_authenticated:
                cart, created = CartSession.objects.get_or_create(
                    user=request.user,
                    is_active=True,
                    defaults={'session_key': f"user-{request.user.id}-{uuid.uuid4().hex[:8]}"})
            else:
                # Create a guest cart with a unique session key
                session_key = request.data.get('session_key') or f"guest-{uuid.uuid4().hex}"
                cart = CartSession.objects.create(session_key=session_key)
                created = True
            
            serializer = self.get_serializer(cart)
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            msg = 'Cart session created' if created else 'Cart session retrieved'
            return APIResponse.created(data=serializer.data, message=msg, correlation_id=correlation_id) if created else APIResponse.success(data=serializer.data, message=msg, correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error creating cart session: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error creating cart session', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=False, methods=['get'], url_path='retrieve_by_session', url_name='retrieve_by_session')
    def retrieve_by_session(self, request, *args, **kwargs):
        """Get a cart by its session key"""
        try:
            correlation_id = get_correlation_id(request)
            session_key = request.query_params.get('session_key')
            if not session_key:
                return APIResponse.bad_request(message='Session key is required', error_id='missing_session_key', correlation_id=correlation_id)
            
            try:
                cart = CartSession.objects.get(session_key=session_key, is_active=True)
                serializer = self.get_serializer(cart)
                return APIResponse.success(data=serializer.data, message='Cart retrieved successfully', correlation_id=correlation_id)
            except CartSession.DoesNotExist:
                return APIResponse.not_found(message='Cart not found', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error retrieving cart by session: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving cart', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=True, methods=['post'], url_path='merge', url_name='merge')
    def merge_carts(self, request, pk=None, *args, **kwargs):
        """Merge items from another cart into this one"""
        try:
            correlation_id = get_correlation_id(request)
            current_cart = self.get_object()
            source_session_key = request.data.get('source_session_key')
            
            if not source_session_key:
                return APIResponse.bad_request(message='Source session key is required', error_id='missing_source_session_key', correlation_id=correlation_id)
            
            try:
                source_cart = CartSession.objects.get(session_key=source_session_key, is_active=True)
                current_cart.merge_with(source_cart)
                
                # Mark the source cart as inactive since it's been merged
                source_cart.is_active = False
                source_cart.save()
                
                AuditTrail.log(operation=AuditTrail.UPDATE, module='ecommerce', entity_type='CartSession', entity_id=current_cart.id, user=request.user, reason=f'Merged cart {source_session_key}', request=request)
                serializer = self.get_serializer(current_cart)
                return APIResponse.success(data=serializer.data, message='Carts merged successfully', correlation_id=correlation_id)
            except CartSession.DoesNotExist:
                return APIResponse.not_found(message='Source cart not found', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error merging carts: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error merging carts', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=True, methods=['post'], url_path='clear', url_name='clear')
    def clear(self, request, pk=None, *args, **kwargs):
        """Clear all items from the cart"""
        try:
            correlation_id = get_correlation_id(request)
            cart = self.get_object()
            cart.clear()
            AuditTrail.log(operation=AuditTrail.UPDATE, module='ecommerce', entity_type='CartSession', entity_id=cart.id, user=request.user, reason='Cart cleared', request=request)
            serializer = self.get_serializer(cart)
            return APIResponse.success(data=serializer.data, message='Cart cleared successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error clearing cart: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error clearing cart', error_id=str(e), correlation_id=get_correlation_id(request))


class CartItemViewSet(BaseModelViewSet):
    """
    API endpoint for managing items in a cart.
    Requires a cart_id parameter for all operations.
    """
    serializer_class = CartItemSerializer
    
    def get_permissions(self):
        # Allow guest cart operations with valid session key
        if 'session_key' in self.request.query_params or 'session_key' in self.request.data:
            return [AllowAny()]
        return [IsAuthenticated()]
    
    def get_cart(self):
        """Get the cart to which items will be added/removed."""
        # First try to get cart from session key (for guests)
        session_key = self.request.query_params.get('session_key') or self.request.data.get('session_key')
        if session_key:
            return get_object_or_404(CartSession, session_key=session_key, is_active=True)
        
        # Next try to get cart from cart_id parameter
        cart_id = self.request.query_params.get('cart_id') or self.request.data.get('cart_id')
        if cart_id:
            # Ensure user has access to this cart
            if self.request.user.is_authenticated:
                return get_object_or_404(CartSession, id=cart_id, user=self.request.user, is_active=True)
            return get_object_or_404(CartSession, id=cart_id, user__isnull=True, is_active=True)
        
        # Finally, try to get the user's default cart
        if self.request.user.is_authenticated:
            cart, _ = CartSession.objects.get_or_create(
                user=self.request.user,
                is_active=True,
                defaults={'session_key': f"user-{self.request.user.id}-{uuid.uuid4().hex[:8]}"})
            return cart
            
        raise Http404("Cart not found. Please provide a valid cart_id or session_key.")
    
    def get_queryset(self):
        try:
            cart = self.get_cart()
            return CartItem.objects.filter(cart=cart).select_related('stock_item')
        except Http404:
            return CartItem.objects.none()
    
    def create(self, request, *args, **kwargs):
        """Add an item to the cart"""
        try:
            correlation_id = get_correlation_id(request)
            cart = self.get_cart()
            serializer = self.get_serializer(data=request.data, context={'cart': cart})
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Cart item validation failed', errors=serializer.errors, correlation_id=correlation_id)
            
            with transaction.atomic():
                instance = serializer.save()
                AuditTrail.log(operation=AuditTrail.CREATE, module='ecommerce', entity_type='CartItem', entity_id=instance.id, user=request.user, reason=f'Added item to cart', request=request)
            
            # Return the cart with updated items
            cart_serializer = CartSessionSerializer(cart, context=self.get_serializer_context())
            return APIResponse.created(data=cart_serializer.data, message='Item added to cart', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error adding item to cart: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error adding item to cart', error_id=str(e), correlation_id=get_correlation_id(request))
    
    def update(self, request, *args, **kwargs):
        """Update cart item quantity"""
        try:
            correlation_id = get_correlation_id(request)
            instance = self.get_object()
            cart = self.get_cart()
            
            # Ensure the item belongs to the cart
            if instance.cart != cart:
                return APIResponse.bad_request(message='Item does not belong to this cart', error_id='cart_item_mismatch', correlation_id=correlation_id)
                
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Update validation failed', errors=serializer.errors, correlation_id=correlation_id)
            serializer.save()
            
            AuditTrail.log(operation=AuditTrail.UPDATE, module='ecommerce', entity_type='CartItem', entity_id=instance.id, user=request.user, reason='Updated cart item', request=request)
            
            # Return the cart with updated items
            cart_serializer = CartSessionSerializer(cart, context=self.get_serializer_context())
            return APIResponse.success(data=cart_serializer.data, message='Cart item updated', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error updating cart item: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error updating cart item', error_id=str(e), correlation_id=get_correlation_id(request))
    
    def destroy(self, request, *args, **kwargs):
        """Remove an item from the cart"""
        try:
            correlation_id = get_correlation_id(request)
            instance = self.get_object()
            cart = self.get_cart()
            
            # Ensure the item belongs to the cart
            if instance.cart != cart:
                return APIResponse.bad_request(message='Item does not belong to this cart', error_id='cart_item_mismatch', correlation_id=correlation_id)
            
            AuditTrail.log(operation=AuditTrail.DELETE, module='ecommerce', entity_type='CartItem', entity_id=instance.id, user=request.user, reason='Removed item from cart', request=request)
            instance.delete()
            
            # Return the cart with updated items
            cart_serializer = CartSessionSerializer(cart, context=self.get_serializer_context())
            return APIResponse.success(data=cart_serializer.data, message='Item removed from cart', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error removing cart item: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error removing cart item', error_id=str(e), correlation_id=get_correlation_id(request))


class SavedForLaterViewSet(BaseModelViewSet):
    """
    API endpoint for managing items saved for later.
    Only authenticated users can save items.
    """
    serializer_class = SavedForLaterSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return SavedForLater.objects.filter(user=self.request.user).select_related('stock_item')
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    def create(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Save for later validation failed', errors=serializer.errors, correlation_id=correlation_id)
            instance = serializer.save(user=request.user)
            AuditTrail.log(operation=AuditTrail.CREATE, module='ecommerce', entity_type='SavedForLater', entity_id=instance.id, user=request.user, reason='Item saved for later', request=request)
            return APIResponse.created(data=self.get_serializer(instance).data, message='Item saved for later', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error saving item for later: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error saving item', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=True, methods=['post'])
    def move_to_cart(self, request, pk=None):
        """Move a saved item to the user's cart"""
        try:
            correlation_id = get_correlation_id(request)
            saved_item = self.get_object()
            
            # Get or create user's cart
            cart, _ = CartSession.objects.get_or_create(
                user=request.user,
                is_active=True,
                defaults={'session_key': f"user-{request.user.id}-{uuid.uuid4().hex[:8]}"})
            
            # Add item to cart
            CartItem.objects.create(
                cart=cart,
                stock_item=saved_item.stock_item,
                selling_price=saved_item.stock_item.selling_price or saved_item.stock_item.discount_price,
                quantity=1,
                variant_info=saved_item.variant_info
            )
            
            # Delete the saved item
            AuditTrail.log(operation=AuditTrail.DELETE, module='ecommerce', entity_type='SavedForLater', entity_id=saved_item.id, user=request.user, reason='Moved item to cart', request=request)
            saved_item.delete()
            
            # Return the cart with the new item
            cart_serializer = CartSessionSerializer(cart, context=self.get_serializer_context())
            return APIResponse.success(data=cart_serializer.data, message='Item moved to cart', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error moving item to cart: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error moving item to cart', error_id=str(e), correlation_id=get_correlation_id(request))
