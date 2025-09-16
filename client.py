from __future__ import annotations

from typing import Optional

import httpx

try:
    from .config import UW_BASE_URL, REQUEST_TIMEOUT_SECONDS
except ImportError:  # script mode fallback
    from config import UW_BASE_URL, REQUEST_TIMEOUT_SECONDS


_async_client: Optional[httpx.AsyncClient] = None


async def get_client() -> httpx.AsyncClient:
    """Shared AsyncClient with single-connection limits.

    Grounded in uwapi/services/uw_client.py:
    - base_url = https://api.unusualwhales.com
    - timeout = 30.0
    - limits = max_connections=1, max_keepalive_connections=1
    - Accept: application/json
    """
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            base_url=UW_BASE_URL,
            timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            headers={"Accept": "application/json"},
        )
    return _async_client


async def close_client() -> None:
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None


