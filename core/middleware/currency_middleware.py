"""
Currency Context Middleware

Automatically sets the active currency context from the frontend currency switcher.
Syncs currency selection across frontend and backend.
"""
from core.currency import CurrencyService
import logging

logger = logging.getLogger(__name__)


class CurrencyContextMiddleware:
    """
    Middleware that automatically sets the active currency for each request.

    How it works:
    1. Frontend sends X-Currency header when user switches currency
    2. Middleware reads header and sets active currency in request context
    3. All currency operations in views use this active currency
    4. Currency is persisted to session for future requests

    Usage in views:
        from core.currency import CurrencyService

        def my_view(request):
            # Get active currency from request
            active_currency = CurrencyService.get_active_currency(request)

            # Convert amount to active currency
            converted = CurrencyService.convert_to_active(1000, 'KES', request)

            # Format in active currency
            formatted = CurrencyService.format_amount(1000, active_currency)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if frontend sent currency header
        currency_header = request.headers.get('X-Currency')

        if currency_header:
            # Set as active currency for this request
            CurrencyService.set_active_currency(currency_header, request)
            logger.debug(f"Set active currency from header: {currency_header}")
        else:
            # Get currency from session or defaults
            active_currency = CurrencyService.get_active_currency(request)
            logger.debug(f"Active currency for request: {active_currency}")

        # Add active currency to request for easy access
        request.active_currency = CurrencyService.get_active_currency(request)

        # Process request
        response = self.get_response(request)

        # Add current active currency to response headers (for frontend sync)
        response['X-Active-Currency'] = request.active_currency

        return response

    def process_exception(self, request, exception):
        """Clear thread-local currency on exception."""
        CurrencyService.clear_active_currency()
        return None
