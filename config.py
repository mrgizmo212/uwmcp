from __future__ import annotations

import os
from typing import Optional


def get_env(var_name: str) -> Optional[str]:
    """Return trimmed environment variable or None.

    Mirrors pattern used by uwapi to avoid surprises.
    """
    value = os.getenv(var_name)
    if value is not None:
        return value.strip()
    return None


# Defaults align with uwapi upstream
UW_BASE_URL: str = get_env("UW_BASE_URL") or "https://api.unusualwhales.com"
UW_API_KEY: Optional[str] = get_env("UW_API_KEY")
UW_BEARER_TOKEN: Optional[str] = get_env("UW_BEARER_TOKEN")

# Network
REQUEST_TIMEOUT_SECONDS: float = float(get_env("UW_TIMEOUT_SECONDS") or 30.0)


