from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import CartSession
from .coupons import Coupon, CartCoupon
from .serializers import CartSessionSerializer, CouponSerializer

class CouponViewSet(viewsets.ModelViewSet):
    queryset = Coupon.objects.filter(is_active=True)
    serializer_class = CouponSerializer
    
    @action(detail=False, methods=['get'], url_path='available', url_name='available')
    def available(self, request):
        """Get all available coupons"""
        # Get active coupons that are not expired
        today = timezone.now().date()
        coupons = Coupon.objects.filter(
            is_active=True,
            #start_date__lte=today,
            end_date__gt=today
        )
        print(coupons)
        
        # Check for usage limitations
        coupons = [coupon for coupon in coupons if coupon.is_valid_for_use()]
        
        serializer = self.get_serializer(coupons, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'], url_path='details')
    def details(self, request, pk=None):
        """Get details for a specific coupon by code"""
        try:
            coupon = Coupon.objects.get(code__iexact=pk, is_active=True)
            serializer = self.get_serializer(coupon)
            return Response(serializer.data)
        except Coupon.DoesNotExist:
            return Response({'error': 'Coupon not found'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=False, methods=['post'])
    def validate(self, request):
        """Validate a coupon code without applying it"""
        code = request.data.get('code')
        cart_id = request.data.get('cart_id')
        shipping_fee = request.data.get('shipping_fee', 0)
        
        if not code:
            return Response({'error': 'Coupon code is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        if not cart_id:
            return Response({'error': 'Cart ID is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            cart = CartSession.objects.get(id=cart_id)
        except CartSession.DoesNotExist:
            return Response({'error': 'Cart not found'}, status=status.HTTP_404_NOT_FOUND)
            
        try:
            coupon = Coupon.objects.get(code__iexact=code, is_active=True)
        except Coupon.DoesNotExist:
            return Response({'error': 'Invalid coupon code'}, status=status.HTTP_404_NOT_FOUND)
            
        # Check coupon validity
        cart_total = cart.get_subtotal()
        is_valid, message = coupon.is_valid(cart_total, request.user if request.user.is_authenticated else None)
        
        if not is_valid:
            return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)
            
        # Calculate potential discount
        discount_amount = coupon.calculate_discount(cart_total, shipping_fee)
        
        return Response({
            'valid': True,
            'message': 'Coupon is valid',
            'discount_amount': discount_amount,
            'coupon_type': coupon.discount_type,
            'coupon_value': coupon.discount_value
        })
        
    @action(detail=False, methods=['post'])
    def apply(self, request):
        """Apply a coupon to a cart"""
        code = request.data.get('code')
        cart_id = request.data.get('cart_id')
        
        if not code:
            return Response({'error': 'Coupon code is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        if not cart_id:
            return Response({'error': 'Cart ID is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            cart = CartSession.objects.get(id=cart_id)
        except CartSession.DoesNotExist:
            return Response({'error': 'Cart not found'}, status=status.HTTP_404_NOT_FOUND)
            
        try:
            coupon = Coupon.objects.get(code__iexact=code, is_active=True)
        except Coupon.DoesNotExist:
            return Response({'error': 'Invalid coupon code'}, status=status.HTTP_404_NOT_FOUND)
            
        # Apply coupon to cart
        success, message = coupon.apply_to_cart(
            cart, 
            request.user if request.user.is_authenticated else None
        )
        
        if not success:
            return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)
            
        # Get updated cart with coupon applied
        serializer = CartSessionSerializer(cart)
        
        return Response({
            'success': True,
            'message': message,
            'cart': serializer.data
        })
        
    @action(detail=False, methods=['post'])
    def remove(self, request):
        """Remove a coupon from a cart"""
        cart_id = request.data.get('cart_id')
        
        if not cart_id:
            return Response({'error': 'Cart ID is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            cart = CartSession.objects.get(id=cart_id)
        except CartSession.DoesNotExist:
            return Response({'error': 'Cart not found'}, status=status.HTTP_404_NOT_FOUND)
            
        # Remove coupon from cart if exists
        try:
            cart_coupon = CartCoupon.objects.get(cart=cart)
            cart_coupon.delete()
            
            return Response({
                'success': True,
                'message': 'Coupon removed successfully'
            })
        except CartCoupon.DoesNotExist:
            return Response({'error': 'No coupon applied to this cart'}, status=status.HTTP_404_NOT_FOUND)
