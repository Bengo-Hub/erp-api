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

User = get_user_model()


class CartSessionViewSet(viewsets.ModelViewSet):
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
        
        serializer = self.get_serializer(cart)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], url_path='retrieve_by_session', url_name='retrieve_by_session')
    def retrieve_by_session(self, request, *args, **kwargs):
        """Get a cart by its session key"""
        session_key = request.query_params.get('session_key')
        if not session_key:
            return Response({"error": "Session key required"}, status=status.HTTP_400_BAD_REQUEST)
        
        cart = get_object_or_404(CartSession, session_key=session_key, is_active=True)
        serializer = self.get_serializer(cart)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='merge', url_name='merge')
    def merge_carts(self, request, pk=None, *args, **kwargs):
        """Merge items from another cart into this one"""
        current_cart = self.get_object()
        source_session_key = request.data.get('source_session_key')
        
        if not source_session_key:
            return Response({"error": "Source session key required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            source_cart = CartSession.objects.get(session_key=source_session_key, is_active=True)
            current_cart.merge_with(source_cart)
            
            # Mark the source cart as inactive since it's been merged
            source_cart.is_active = False
            source_cart.save()
            
            serializer = self.get_serializer(current_cart)
            return Response(serializer.data)
        except CartSession.DoesNotExist:
            return Response({"error": "Source cart not found"}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'], url_path='clear', url_name='clear')
    def clear(self, request, pk=None, *args, **kwargs):
        """Clear all items from the cart"""
        cart = self.get_object()
        cart.clear()
        serializer = self.get_serializer(cart)
        return Response(serializer.data)


class CartItemViewSet(viewsets.ModelViewSet):
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
            return CartItem.objects.filter(cart=cart)
        except Http404:
            return CartItem.objects.none()
    
    def create(self, request, *args, **kwargs):
        """Add an item to the cart"""
        cart = self.get_cart()
        serializer = self.get_serializer(data=request.data, context={'cart': cart})
        serializer.is_valid(raise_exception=True)
        
        with transaction.atomic():
            serializer.save()
            
        # Return the cart with updated items
        cart_serializer = CartSessionSerializer(cart, context=self.get_serializer_context())
        return Response(cart_serializer.data, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        """Update cart item quantity"""
        instance = self.get_object()
        cart = self.get_cart()
        
        # Ensure the item belongs to the cart
        if instance.cart != cart:
            return Response({"error": "Item does not belong to the specified cart"}, 
                            status=status.HTTP_400_BAD_REQUEST)
                
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Return the cart with updated items
        cart_serializer = CartSessionSerializer(cart, context=self.get_serializer_context())
        return Response(cart_serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        """Remove an item from the cart"""
        instance = self.get_object()
        cart = self.get_cart()
        
        # Ensure the item belongs to the cart
        if instance.cart != cart:
            return Response({"error": "Item does not belong to the specified cart"}, 
                            status=status.HTTP_400_BAD_REQUEST)
                
        instance.delete()
        
        # Return the cart with updated items
        cart_serializer = CartSessionSerializer(cart, context=self.get_serializer_context())
        return Response(cart_serializer.data)


class SavedForLaterViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing items saved for later.
    Only authenticated users can save items.
    """
    serializer_class = SavedForLaterSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return SavedForLater.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def move_to_cart(self, request, pk=None):
        """Move a saved item to the user's cart"""
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
        saved_item.delete()
        
        # Return the cart with the new item
        cart_serializer = CartSessionSerializer(cart, context=self.get_serializer_context())
        return Response(cart_serializer.data)
