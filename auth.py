from __future__ import annotations

from typing import Dict

from .config import UW_API_KEY, UW_BEARER_TOKEN


def build_auth_headers() -> Dict[str, str]:
    """Construct auth headers matching uwapi semantics.

    Grounded in uwapi/services/uw_client.py:
    - X-API-Key from UW_API_KEY
    - Authorization: Bearer from UW_BEARER_TOKEN
    """
    headers: Dict[str, str] = {}
    # uwapi/services/uw_client.py reference:
    # def _build_auth_headers() -> dict:
    #     ... if api_key: headers["X-API-Key"] = api_key
    #     if bearer: headers["Authorization"] = f"Bearer {bearer}"
    if UW_API_KEY:
        headers["X-API-Key"] = UW_API_KEY
    if UW_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {UW_BEARER_TOKEN}"
    return headers


