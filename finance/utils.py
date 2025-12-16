"""Utility helpers for the finance app."""
from typing import Iterable, Optional


def _safe_str(val) -> str:
    if val is None:
        return ''
    if isinstance(val, str):
        return val
    try:
        return str(val)
    except Exception:
        # Fallback to common attribute
        return getattr(val, 'name', '') or ''


def format_location_address(location, fields: Optional[Iterable[str]] = None) -> str:
    """Build a sane, deduplicated address string from a location-like object.

    - Converts non-string values (like Country objects) to strings safely
    - Removes empty parts
    - Deduplicates parts case-insensitively while preserving order

    Args:
        location: object with attributes (e.g., building_name, street_name, city, county, state, country)
        fields: optional iterable of attribute names to consider

    Returns:
        A single-line address string (comma separated) or empty string.
    """
    if not location:
        return ''

    if fields is None:
        fields = ['building_name', 'street_name', 'city', 'county', 'state', 'country']

    seen = set()
    parts = []
    for f in fields:
        try:
            raw = getattr(location, f, None)
        except Exception:
            raw = None
        v = _safe_str(raw).strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(v)

    return ', '.join(parts)
