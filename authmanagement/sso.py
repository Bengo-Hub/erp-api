"""
SSO integration for the ERP as an auth-service client.

The ERP no longer issues its own access tokens for API clients. Instead it trusts
RS256 JWTs minted by the platform auth-service, validating them locally against the
auth-service JWKS endpoint (cached) and just-in-time (JIT) provisioning a thin local
``CustomUser`` shadow so existing foreign keys (HRM, procurement, etc.) keep working.

Canonical contracts:
  - shared-docs/sso-integration-guide.md
  - shared-docs/login-flow-contract.md
  - shared-docs/subscription-gating-guide.md
  - shared-docs/TRINITY-AUTHORIZATION-PATTERN.md

Everything here is gated by ``settings.SSO_ENABLED`` so the legacy token/session auth
keeps working until the cutover is complete.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import authentication, exceptions

logger = logging.getLogger(__name__)

User = get_user_model()


# ---------------------------------------------------------------------------
# JWKS client (cached)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _jwks_client() -> "jwt.PyJWKClient":
    """Return a process-cached PyJWKClient pointed at the auth-service JWKS."""
    jwks_url = getattr(settings, "AUTH_JWKS_URL", "")
    if not jwks_url:
        raise exceptions.AuthenticationFailed("SSO is enabled but AUTH_JWKS_URL is not configured.")
    # PyJWKClient caches keys in-memory and refreshes on unknown kid.
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=getattr(settings, "AUTH_JWKS_TTL", 600))


def validate_token(token: str) -> dict[str, Any]:
    """Validate a bearer JWT against the auth-service JWKS and return its claims.

    Raises rest_framework AuthenticationFailed on any validation problem.
    """
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        options = {"require": ["exp", "sub"]}
        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "options": options,
            "leeway": getattr(settings, "AUTH_JWT_LEEWAY", 30),
        }
        audience = getattr(settings, "AUTH_AUDIENCE", "") or None
        issuer = getattr(settings, "AUTH_ISSUER", "") or None
        if audience:
            decode_kwargs["audience"] = audience
        if issuer:
            decode_kwargs["issuer"] = issuer
        return jwt.decode(token, signing_key.key, **decode_kwargs)
    except exceptions.AuthenticationFailed:
        raise
    except jwt.ExpiredSignatureError:
        raise exceptions.AuthenticationFailed("Access token has expired.")
    except jwt.InvalidTokenError as exc:
        raise exceptions.AuthenticationFailed(f"Invalid access token: {exc}")
    except Exception as exc:  # JWKS fetch / network / key errors
        logger.warning("SSO token validation error: %s", exc)
        raise exceptions.AuthenticationFailed("Could not validate access token.")


# ---------------------------------------------------------------------------
# Claims wrapper
# ---------------------------------------------------------------------------
class Claims:
    """Convenience wrapper over the decoded JWT claims.

    Mirrors the JWT shape documented in shared-docs/sso-integration-guide.md so the
    subscription-gating and authorization layers can read consistent fields.
    """

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw or {}

    # identity
    @property
    def sub(self) -> str:
        return str(self.raw.get("sub", ""))

    @property
    def email(self) -> str:
        return self.raw.get("email", "") or ""

    @property
    def first_name(self) -> str:
        return self.raw.get("given_name") or self.raw.get("first_name") or ""

    @property
    def last_name(self) -> str:
        return self.raw.get("family_name") or self.raw.get("last_name") or ""

    # tenant / outlet context
    @property
    def tenant_id(self) -> str:
        return self.raw.get("tenant_id", "") or ""

    @property
    def tenant_slug(self) -> str:
        return self.raw.get("tenant_slug", "") or ""

    @property
    def outlet_id(self) -> str:
        return self.raw.get("outlet_id", "") or ""

    @property
    def outlet_code(self) -> str:
        return self.raw.get("outlet_code", "") or ""

    @property
    def outlet_use_case(self) -> str:
        return self.raw.get("outlet_use_case", "") or ""

    @property
    def is_hq_user(self) -> bool:
        return bool(self.raw.get("is_hq_user"))

    def can_access_all_outlets(self) -> bool:
        """HQ users, platform owners and superusers bypass outlet-scoped filtering."""
        return self.is_hq_user or self.is_platform_owner or self.is_superuser

    # authorization
    @property
    def roles(self) -> list[str]:
        return list(self.raw.get("roles", []) or [])

    @property
    def permissions(self) -> list[str]:
        return list(self.raw.get("permissions", []) or [])

    @property
    def is_platform_owner(self) -> bool:
        return bool(self.raw.get("is_platform_owner") or self.raw.get("is_platform_admin"))

    @property
    def is_superuser(self) -> bool:
        return bool(self.raw.get("is_superuser"))

    # subscription (baked into the JWT at issuance by auth-service)
    @property
    def sub_status(self) -> str:
        return (self.raw.get("sub_status", "") or "").upper()

    @property
    def sub_features(self) -> list[str]:
        return list(self.raw.get("sub_features", []) or [])

    @property
    def sub_limits(self) -> dict[str, Any]:
        return dict(self.raw.get("sub_limits", {}) or {})

    @property
    def sub_expires(self) -> int:
        try:
            return int(self.raw.get("sub_expires", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def billing_mode(self) -> str:
        return (self.raw.get("billing_mode", "") or "").lower()

    @property
    def is_demo(self) -> bool:
        return bool(self.raw.get("is_demo"))

    def has_feature(self, code: str) -> bool:
        return code in self.sub_features

    def is_subscription_active(self) -> bool:
        # service_charge billing and demo tenants bypass subscription gating entirely.
        if self.billing_mode == "service_charge" or self.is_demo:
            return True
        # Absence of subscription claims is treated as active so non-gated tenants
        # (and tokens minted before subscription enrichment) are not blocked.
        if "sub_status" not in self.raw:
            return True
        return self.sub_status in {"ACTIVE", "TRIAL", "TRIALING"}


# ---------------------------------------------------------------------------
# JIT provisioning
# ---------------------------------------------------------------------------
def get_or_provision_user(claims: Claims):
    """Find or create the local ``CustomUser`` shadow for the given claims.

    Matches first on ``external_id`` (auth-service sub), then on email (linking a
    pre-existing local account to its SSO identity). Keeps the shadow's basic fields
    in sync but never stores a usable password — auth lives in auth-service.
    """
    if not claims.sub:
        raise exceptions.AuthenticationFailed("Token missing 'sub' claim.")

    user = User.objects.filter(external_id=claims.sub).first()
    if user is None and claims.email:
        user = User.objects.filter(email__iexact=claims.email).first()
        if user is not None and not user.external_id:
            user.external_id = claims.sub
            user.save(update_fields=["external_id"])

    if user is None:
        user = User.objects.create(
            external_id=claims.sub,
            email=claims.email or f"{claims.sub}@sso.local",
            first_name=claims.first_name or (claims.email.split("@")[0] if claims.email else "User"),
            last_name=claims.last_name or "",
            is_active=True,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        logger.info("JIT-provisioned SSO user %s (sub=%s)", user.email, claims.sub)

    # Keep platform/staff flags in sync with the token (read-only mirror).
    desired_super = claims.is_superuser or claims.is_platform_owner
    if desired_super and not user.is_superuser:
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=["is_superuser", "is_staff"])

    _assign_service_roles(user, claims)
    return user


# Map global JWT roles → ERP-local Django group (Layer-3 service role) per Trinity §JIT.
_GLOBAL_TO_ERP_ROLE = {
    "superuser": "erp_admin",
    "admin": "erp_admin",
    "manager": "erp_manager",
    "staff": "erp_staff",
    "member": "erp_staff",
}


def _assign_service_roles(user, claims: "Claims") -> None:
    """Ensure the SSO user has at least one ERP service-level role (Django group).

    Idempotent; only adds a default role when the user has no ERP group yet, so manual
    role changes by an admin are not overwritten on every request.
    """
    try:
        from django.contrib.auth.models import Group

        if user.groups.exists():
            return
        target = "erp_admin" if (claims.is_superuser or claims.is_platform_owner) else None
        if target is None:
            for r in claims.roles:
                if r in _GLOBAL_TO_ERP_ROLE:
                    target = _GLOBAL_TO_ERP_ROLE[r]
                    break
        target = target or "erp_staff"
        group, _ = Group.objects.get_or_create(name=target)
        user.groups.add(group)
    except Exception as exc:  # never block auth on role assignment
        logger.warning("JIT role assignment failed for %s: %s", getattr(user, "email", "?"), exc)


# ---------------------------------------------------------------------------
# DRF authentication class
# ---------------------------------------------------------------------------
class SSOJWTAuthentication(authentication.BaseAuthentication):
    """Authenticate DRF requests using an auth-service RS256 JWT.

    Returns ``None`` (rather than failing) when SSO is disabled or there is no bearer
    token, so the legacy auth classes still run during the transition period.
    Reuses claims attached by :class:`SSOAuthenticationMiddleware` when present.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        if not getattr(settings, "SSO_ENABLED", False):
            return None

        claims: Optional[Claims] = getattr(request, "auth_claims", None)
        if claims is None:
            token = _extract_bearer(request)
            if not token:
                return None
            claims = Claims(validate_token(token))
            request.auth_claims = claims

        user = get_or_provision_user(claims)
        return (user, claims)

    def authenticate_header(self, request):
        return self.keyword


def _extract_bearer(request) -> str:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return ""
