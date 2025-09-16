from __future__ import annotations

import os

try:
    # When executed as a module (python -m uwmcp.run_http)
    from .server import get_server
except ImportError:  # Script execution fallback (python run_http.py)
    from server import get_server


if __name__ == "__main__":
    mcp = get_server()
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http")


