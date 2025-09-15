from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastmcp import FastMCP  # grounded by fastmcp/examples/simple_echo.py

# Support both package execution (python -m uwmcp.run_http) and script execution (python run_http.py)
try:
    from ..schemas import (
        load_spec,
        list_paths,
        get_operation,
        get_parameters_shallow,
        extract_response_schema_shallow,
        get_registry_shallow,
        get_allowed_query_param_names,
        get_path_param_names,
    )
    from ..auth import build_auth_headers
    from ..client import get_client
except ImportError:  # pragma: no cover - fallback for script mode on hosts like Render
    from schemas import (
        load_spec,
        list_paths,
        get_operation,
        get_parameters_shallow,
        extract_response_schema_shallow,
        get_registry_shallow,
        get_allowed_query_param_names,
        get_path_param_names,
    )
    from auth import build_auth_headers
    from client import get_client


mcp = FastMCP(
    "uwmcp",
    instructions="""
Agent workflow:
1) search_endpoints [query] → discover GET endpoints
2) get_available_params(path) → see allowed path/query params (shallow schemas)
3) call_get(path, params[, headers]) → execute request

Behavior: uses uwmcp/openapi.yaml; shallow OpenAPI registry (no deep $ref);
validates path/query names and reports errors; no response caching.
""",
)


def _param_alias(param: Dict[str, Any]) -> Optional[str]:
    # uwapi uses Query(..., alias='expirations[]') etc.
    # In OpenAPI, alias typically appears as `name` at request time; we return both.
    # We will preserve original `name` and include `x-alias` if present in schema extras.
    # The uwapi meta inlines schemas; alias is not formalized there, but we include space for it.
    return param.get("x-alias")  # Optional future enhancement


@mcp.tool()
def search_endpoints(query: Optional[str] = None) -> Dict[str, Any]:
    """Discover GET endpoints with parameters and response schemas.

    - Returns: { paths: [{ path, summary, tags, parameters: [{name, in, required, schema}], responseSchema }], count }
    - Optional query filters by substring in path/summary/tags.
    """
    spec = load_spec()
    results: List[Dict[str, Any]] = []
    for path in list_paths(spec):
        op = get_operation(spec, path, method="get")
        if not op:
            continue
        summary = op.get("summary") or op.get("description") or ""
        tags = op.get("tags") or []
        params = get_parameters_shallow(spec, op)
        response_schema = extract_response_schema_shallow(spec, op)

        entry = {
            "path": path,
            "summary": summary,
            "tags": tags,
            "parameters": [
                {
                    "name": p.get("name"),
                    "in": p.get("in"),
                    "required": p.get("required", False) or (p.get("in") == "path"),
                    "schema": p.get("schema"),
                }
                for p in params
            ],
            "responseSchema": response_schema,
        }

        if query:
            q = query.lower()
            hay = " ".join([
                path,
                summary or "",
                " ".join(tags),
            ]).lower()
            if q not in hay:
                continue
        results.append(entry)

    return {"paths": results, "count": len(results)}


def _split_params_for_path(path_template: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Split params into path and query based on placeholders in the path template."""
    import re

    path_keys = set(re.findall(r"\{([^/}]+)\}", path_template))
    path_params: Dict[str, Any] = {}
    query_params: Dict[str, Any] = {}
    for k, v in (params or {}).items():
        if k in path_keys:
            path_params[k] = v
        else:
            query_params[k] = v
    return path_params, query_params


def _format_path(path_template: str, path_params: Dict[str, Any]) -> str:
    path = path_template
    for k, v in (path_params or {}).items():
        path = path.replace("{" + k + "}", str(v))
    return path


@mcp.tool()
async def call_get(path: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
    """Execute a GET request for a given OpenAPI path using provided params.

    - Path params substituted into the path; remaining params sent as query
    - Auth headers added per uwapi semantics, can be overridden/augmented via headers
    """
    return await call_get_internal(path, params, headers)


async def call_get_internal(path: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
    """Internal helper to execute GET requests; used by other tool modules.

    Note: This function is callable directly from Python code. The user-facing
    tool remains exposed as `call_get` via the decorator above.
    """
    client = await get_client()
    # Build auth headers
    upstream_headers = {**build_auth_headers()}
    if headers:
        upstream_headers.update(headers)

    # Validate path and parameter names using shallow registry (no response caching)
    registry = get_registry_shallow()
    if path not in registry:
        return {"error": f"Unknown GET path: {path}", "known_paths": sorted(list(registry.keys()))[:50]}

    allowed_query = get_allowed_query_param_names(path)
    required_path = get_path_param_names(path)

    path_params, query_params = _split_params_for_path(path, params or {})

    missing_path = sorted(list(required_path - set(path_params.keys())))
    if missing_path:
        return {"error": "Missing path parameters", "missing": missing_path, "path": path}

    unknown_query = sorted([k for k in (query_params or {}).keys() if k not in allowed_query])
    if unknown_query:
        return {
            "error": "Unknown query parameters",
            "unknown": unknown_query,
            "allowed": sorted(list(allowed_query)),
            "path": path,
        }

    real_path = _format_path(path, path_params)

    # Make request, mirror uwapi proxy style
    resp = await client.get(real_path, params=query_params, headers=upstream_headers)
    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        try:
            return resp.json()
        except ValueError:
            pass
    return {
        "status": resp.status_code,
        "headers": {k: v for k, v in resp.headers.items()},
        "content": resp.content.decode("utf-8", errors="replace"),
        "media_type": content_type,
    }



@mcp.tool()
def get_available_params(path: str) -> Dict[str, Any]:
    """List allowed path and query parameters (with shallow schema summaries) for a given GET endpoint path."""
    registry = get_registry_shallow()
    entry = registry.get(path)
    if not entry:
        return {"error": f"Unknown GET path: {path}", "known_paths": sorted(list(registry.keys()))[:50]}

    params = entry.get("parameters") or []
    path_param_names = set(entry.get("pathParamNames", []) or [])

    return {
        "path": path,
        "path_parameters": [p for p in params if p.get("name") in path_param_names],
        "query_parameters": [p for p in params if p.get("in") == "query"],
        "tags": entry.get("tags") or [],
        "summary": entry.get("summary") or "",
    }

