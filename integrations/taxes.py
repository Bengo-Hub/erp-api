"""
Tax-rate accessor — treasury-api is the single source of truth for taxes (VAT/WHT/
excise) and KRA/eTIMS (CROSS-SERVICE-DATA-OWNERSHIP.md). The ERP no longer owns sales
tax; when a tenant-configurable rate is needed (e.g. on a document) it is fetched from
treasury S2S and cached.

Note: payroll statutory deductions (PAYE/NHIF/NSSF/Housing Levy) are HR payroll-engine
rules computed locally in hrm.payroll — they are NOT sales tax and are not fetched here.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.core.cache import cache

from .service_client import ServiceError, get_client

logger = logging.getLogger(__name__)

_TTL = 60 * 60  # 1h


def get_tax_codes(tenant_id: str, request=None) -> list[dict[str, Any]]:
    """Return the tenant's active tax codes from treasury (cached). [] on failure."""
    if not tenant_id:
        return []
    key = f"erp:taxcodes:{tenant_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        client = get_client("treasury", request=request)
        data = client.get(f"/api/v1/s2s/{tenant_id}/taxes")
    except ServiceError as exc:
        logger.warning("get_tax_codes(%s) failed: %s", tenant_id, exc)
        return []
    codes = data.get("tax_codes", data) if isinstance(data, dict) else data
    codes = codes if isinstance(codes, list) else []
    cache.set(key, codes, _TTL)
    return codes


def get_tax_code(tenant_id: str, code: str, request=None) -> Optional[dict[str, Any]]:
    """Return a single treasury tax code (e.g. 'VAT-16'), or None."""
    if not tenant_id or not code:
        return None
    for tc in get_tax_codes(tenant_id, request=request):
        if str(tc.get("code") or tc.get("name")) == code:
            return tc
    try:
        client = get_client("treasury", request=request)
        return client.get(f"/api/v1/s2s/{tenant_id}/taxes/{code}")
    except ServiceError:
        return None
