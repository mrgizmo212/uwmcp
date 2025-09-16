from __future__ import annotations

from fastmcp import FastMCP

# Import tool modules so their @mcp.tool decorators register tools
try:
    from .tools.generic import mcp as _generic_mcp  # type: ignore  # noqa: F401
except ImportError:
    from tools.generic import mcp as _generic_mcp  # type: ignore  # noqa: F401


def get_server() -> FastMCP:
    # Reuse the FastMCP instance created in tools.generic
    return _generic_mcp


if __name__ == "__main__":
    get_server().run()


