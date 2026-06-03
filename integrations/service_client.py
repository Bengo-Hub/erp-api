"""
Service-to-service (S2S) HTTP client for calling platform microservices.

Mirrors the Go ``shared-service-client`` behaviour (retry + backoff, internal key
auth, tenant/outlet context propagation) for the Django ERP. Base URLs and the
shared internal key come from settings (env-backed). See
shared-docs/microservice-architecture.md and CROSS-SERVICE-DATA-OWNERSHIP.md.

Usage:
    from integrations.service_client import get_client

    treasury = get_client("treasury", request=request)        # forwards JWT + tenant
    intent = treasury.post("/api/v1/s2s/{}/payments/intents".format(tenant), json=payload)

    inventory = get_client("inventory")                        # service-context only
    item = inventory.get(f"/api/v1/{tenant}/inventory/items/{sku}")
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter

try:  # urllib3 is a hard dependency of requests
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    Retry = None  # type: ignore

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Raised when an S2S call fails (network error or non-2xx response)."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ServiceClient:
    """Thin wrapper over a requests.Session for one downstream service."""

    def __init__(
        self,
        service: str,
        base_url: str,
        *,
        request=None,
        tenant_id: str = "",
        tenant_slug: str = "",
        outlet_id: str = "",
        timeout: float | None = None,
    ):
        self.service = service
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout if timeout is not None else getattr(settings, "SERVICE_CLIENT_TIMEOUT", 10)
        self._session = _build_session()

        # Resolve auth/tenant context: explicit args win, else derive from request claims.
        self._headers: dict[str, str] = {"Accept": "application/json"}
        internal_key = getattr(settings, "INTERNAL_SERVICE_KEY", "")
        if internal_key:
            self._headers["X-API-Key"] = internal_key

        claims = getattr(request, "auth_claims", None) if request is not None else None
        if claims is not None:
            tenant_id = tenant_id or claims.tenant_id
            tenant_slug = tenant_slug or claims.tenant_slug
            outlet_id = outlet_id or claims.outlet_id
            token = _bearer_from_request(request)
            if token:
                self._headers["Authorization"] = f"Bearer {token}"

        if tenant_id:
            self._headers["X-Tenant-ID"] = tenant_id
        if tenant_slug:
            self._headers["X-Tenant-Slug"] = tenant_slug
        if outlet_id:
            self._headers["X-Outlet-ID"] = outlet_id

    # -- verbs -----------------------------------------------------------------
    def get(self, path: str, params: dict | None = None, **kwargs) -> Any:
        return self._request("GET", path, params=params, **kwargs)

    def post(self, path: str, json: Any = None, **kwargs) -> Any:
        return self._request("POST", path, json=json, **kwargs)

    def put(self, path: str, json: Any = None, **kwargs) -> Any:
        return self._request("PUT", path, json=json, **kwargs)

    def patch(self, path: str, json: Any = None, **kwargs) -> Any:
        return self._request("PATCH", path, json=json, **kwargs)

    def delete(self, path: str, **kwargs) -> Any:
        return self._request("DELETE", path, **kwargs)

    # -- core ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        headers = {**self._headers, **kwargs.pop("headers", {})}
        try:
            resp = self._session.request(
                method, url, headers=headers, timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            logger.warning("S2S %s %s -> network error: %s", method, url, exc)
            raise ServiceError(f"{self.service} request failed: {exc}") from exc

        if resp.status_code >= 400:
            body = _safe_json(resp)
            logger.warning("S2S %s %s -> %s %s", method, url, resp.status_code, body)
            raise ServiceError(
                f"{self.service} returned {resp.status_code}",
                status_code=resp.status_code,
                body=body,
            )
        return _safe_json(resp)


def _build_session() -> requests.Session:
    session = requests.Session()
    if Retry is not None:
        retry = Retry(
            total=getattr(settings, "SERVICE_CLIENT_RETRIES", 2),
            backoff_factor=0.3,
            status_forcelist=(502, 503, 504),
            allowed_methods=frozenset(["GET", "POST", "PUT", "PATCH", "DELETE"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    return session


def _bearer_from_request(request) -> str:
    header = request.META.get("HTTP_AUTHORIZATION", "") if request is not None else ""
    parts = header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return ""


def _safe_json(resp: "requests.Response") -> Any:
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


def get_client(service: str, *, request=None, **ctx) -> ServiceClient:
    """Factory: build a :class:`ServiceClient` for a known platform service.

    ``service`` is one of the keys in ``settings.SERVICE_URLS`` (auth, treasury,
    inventory, pos, ordering, notifications, marketflow, subscriptions).
    """
    urls = getattr(settings, "SERVICE_URLS", {})
    base_url = urls.get(service)
    if not base_url:
        raise ServiceError(f"Unknown service '{service}'. Configure SERVICE_URLS[{service!r}].")
    return ServiceClient(service, base_url, request=request, **ctx)
