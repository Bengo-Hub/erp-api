"""
WebSocket authentication middleware for Django Channels.
Supports token-based authentication via query parameters.
"""
from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async

# Lazy imports to avoid AppRegistryNotReady errors
def _get_user_model():
    """Lazy import of User model."""
    from django.contrib.auth import get_user_model
    return get_user_model()

def _get_anonymous_user():
    """Lazy import of AnonymousUser."""
    from django.contrib.auth.models import AnonymousUser
    return AnonymousUser

def _get_token_model():
    """Lazy import of Token model."""
    from rest_framework.authtoken.models import Token
    return Token


@database_sync_to_async
def get_user_from_token(token_key):
    """Get user from token key."""
    AnonymousUser = _get_anonymous_user()
    Token = _get_token_model()
    
    if not token_key:
        return AnonymousUser()
    try:
        token = Token.objects.select_related('user').get(key=token_key)
        return token.user if token.user.is_active else AnonymousUser()
    except Token.DoesNotExist:
        return AnonymousUser()


class TokenAuthMiddleware(BaseMiddleware):
    """
    Token authentication middleware for WebSocket connections.
    
    Supports authentication via:
    1. Query parameter: ?token=<token_key>
    2. Falls back to session authentication if no token provided
    """

    async def __call__(self, scope, receive, send):
        # Only handle WebSocket connections
        if scope["type"] != "websocket":
            return await super().__call__(scope, receive, send)

        # Extract token from query string
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        token_key = query_params.get("token", [None])[0]

        # Try to authenticate with token
        AnonymousUser = _get_anonymous_user()
        if token_key:
            scope["user"] = await get_user_from_token(token_key)
        else:
            # Fall back to anonymous user if no token provided
            # The AuthMiddlewareStack will handle session-based auth
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def TokenAuthMiddlewareStack(inner):
    """Middleware stack that includes token authentication."""
    from channels.auth import AuthMiddlewareStack
    # Token auth runs first, then session auth as fallback
    return TokenAuthMiddleware(AuthMiddlewareStack(inner))

