"""
SSO + subscription-gating Django middlewares for the ERP.

Two cooperating middlewares, both gated by ``settings.SSO_ENABLED``:

1. ``SSOAuthenticationMiddleware`` — decodes the bearer JWT once per request and
   attaches a :class:`authmanagement.sso.Claims` object as ``request.auth_claims``
   (or ``None``). It does NOT enforce anything; it just makes claims available to
   later middleware and to the DRF auth class (which reuses them).

2. ``SubscriptionGatingMiddleware`` — mutations-only enforcement per
   shared-docs/subscription-gating-guide.md: GET/HEAD/OPTIONS always pass; for
   POST/PUT/PATCH/DELETE the tenant must have an active subscription (superusers /
   platform owners bypass) else a 403 with ``code: "subscription_inactive"`` is
   returned so frontends can show an upgrade prompt instead of a login redirect.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.http import JsonResponse
from rest_framework import exceptions

from .sso import Claims, validate_token, _extract_bearer

logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Paths that must never be subscription-gated (health, auth callbacks, webhooks, docs).
_GATING_EXEMPT_PREFIXES = (
    "/health",
    "/api/v1/auth/",
    "/api/v1/webhooks/",
    "/swagger",
    "/redoc",
    "/static/",
    "/media/",
)


class SSOAuthenticationMiddleware:
    """Attach decoded SSO claims to the request (no enforcement)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.auth_claims = None
        if getattr(settings, "SSO_ENABLED", False):
            token = _extract_bearer(request)
            if token:
                try:
                    request.auth_claims = Claims(validate_token(token))
                except exceptions.AuthenticationFailed:
                    # Leave claims as None; DRF auth will produce the 401 for
                    # protected endpoints. Do not block here so public routes work.
                    request.auth_claims = None
        return self.get_response(request)


class SubscriptionGatingMiddleware:
    """Block mutations when the tenant's subscription is inactive."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "SSO_ENABLED", False) or not getattr(
            settings, "SUBSCRIPTION_GATING_ENABLED", False
        ):
            return self.get_response(request)

        if request.method in SAFE_METHODS:
            return self.get_response(request)

        path = request.path or ""
        if any(path.startswith(p) for p in _GATING_EXEMPT_PREFIXES):
            return self.get_response(request)

        claims: Claims | None = getattr(request, "auth_claims", None)
        # No claims => unauthenticated; let the auth layer return 401 rather than 403.
        if claims is None:
            return self.get_response(request)

        if claims.is_superuser or claims.is_platform_owner or claims.is_subscription_active():
            return self.get_response(request)

        return JsonResponse(
            {
                "error": "Your subscription is not active. Please renew to continue.",
                "code": "subscription_inactive",
                "upgrade": True,
            },
            status=403,
        )
