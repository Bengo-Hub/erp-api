"""
Service-level ``GET /api/v1/auth/me`` for the ERP (Layer-3 RBAC enrichment).

Per shared-docs/TRINITY-AUTHORIZATION-PATTERN.md, after SSO login a frontend calls
auth-api ``/api/v1/auth/me`` for identity + global roles, then the service's own
``/auth/me`` for service-level role + fine-grained permissions. This endpoint returns
the ERP's local RBAC (Django groups as service roles + resolved permissions) merged
with the SSO claims, so erp-ui can gate sidebar/buttons on ERP permissions.
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class AuthMeView(APIView):
    """Return the authenticated user's identity + ERP service-level RBAC."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        claims = getattr(request, "auth_claims", None)

        # Service-level role(s) = ERP Django groups; permissions = resolved Django perms.
        service_roles = list(user.groups.values_list("name", flat=True))
        if user.is_superuser:
            permissions = ["*"]  # superuser bypass marker (frontend treats as all)
        else:
            # Return BARE codenames (e.g. "view_employee"), not Django's "app_label.codename".
            # The erp-ui gates sidebar/buttons on bare codenames, so returning the prefixed form
            # made every non-superuser permission check fail (users denied despite having roles).
            permissions = sorted({p.split(".")[-1] for p in user.get_all_permissions()})

        global_roles = claims.roles if claims else []
        return Response({
            "user_id": str(getattr(user, "external_id", "") or user.pk),
            "email": user.email,
            "name": (f"{user.first_name} {user.last_name}").strip() or user.email,
            "global_roles": global_roles,
            "service_role": service_roles[0] if service_roles else "",
            "service_roles": service_roles,
            "permissions": permissions,
            "is_platform_owner": bool(claims.is_platform_owner) if claims else False,
            "is_superuser": bool(user.is_superuser),
            "tenant_id": getattr(request, "tenant_id", "") or (claims.tenant_id if claims else ""),
            "tenant_slug": claims.tenant_slug if claims else "",
            "outlet_id": getattr(request, "outlet_id", "") or (claims.outlet_id if claims else ""),
            "outlet_use_case": claims.outlet_use_case if claims else "",
            "is_hq_user": bool(claims.is_hq_user) if claims else False,
        })
