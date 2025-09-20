from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import json

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
        # Omit alerts and websocket tagged endpoints from discovery
        if any(t in {"alerts", "websocket"} for t in (tags or [])):
            continue
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


def _infer_template_and_params(
    concrete_path: str, registry: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, str]]]:
    """Given a concrete path (e.g., "/api/shorts/NVDA/data"), try to find a
    matching template from the registry (e.g., "/api/shorts/{ticker}/data").

    Returns the matched template path and inferred path params if a single best
    match is found; otherwise returns None.
    """
    def split_segments(p: str) -> List[str]:
        p = (p or "").strip()
        if not p:
            return []
        # Normalize leading/trailing slashes
        p = p if p.startswith("/") else "/" + p
        p = p.rstrip("/")
        return [seg for seg in p.split("/") if seg]

    csegs = split_segments(concrete_path)
    candidates: List[Tuple[int, int, str, Dict[str, str]]] = []
    for template in registry.keys():
        tsegs = split_segments(template)
        if len(tsegs) != len(csegs):
            continue
        inferred: Dict[str, str] = {}
        static_matches = 0
        ok = True
        for tseg, cseg in zip(tsegs, csegs):
            if tseg.startswith("{") and tseg.endswith("}"):
                pname = tseg[1:-1]
                if not pname:
                    ok = False
                    break
                inferred[pname] = cseg
            else:
                if tseg != cseg:
                    ok = False
                    break
                static_matches += 1
        if ok:
            # Higher static_matches preferred; fewer params preferred as tiebreaker
            candidates.append((static_matches, -len(inferred), template, inferred))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    top = candidates[0]
    # If there are multiple with identical score and param count, accept the first deterministically
    _, _, best_template, best_params = top
    return best_template, best_params


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

    effective_path = path
    effective_params: Dict[str, Any] = dict(params or {})

    if effective_path not in registry:
        inferred = _infer_template_and_params(effective_path, registry)
        if inferred:
            template_path, inferred_path_params = inferred
            # Detect conflicts between inferred path params and provided params
            for k, v in inferred_path_params.items():
                if k in effective_params and str(effective_params[k]) != str(v):
                    return {
                        "error": "Path parameter mismatch",
                        "param": k,
                        "from_path": v,
                        "from_params": str(effective_params[k]),
                        "template": template_path,
                    }
            # Merge and switch to template for validation
            for k, v in inferred_path_params.items():
                effective_params.setdefault(k, v)
            effective_path = template_path
        else:
            # Suggest a likely template if any static segments match
            def _best_suggestion(concrete: str) -> Optional[str]:
                csegs = [seg for seg in concrete.strip("/").split("/") if seg]
                best_tpl = None
                best_score = -1
                for tpl in registry.keys():
                    tsegs = [seg for seg in tpl.strip("/").split("/") if seg]
                    if len(tsegs) != len(csegs):
                        continue
                    score = sum(1 for t, c in zip(tsegs, csegs) if not (t.startswith("{") and t.endswith("}")) and t == c)
                    if score > best_score:
                        best_score = score
                        best_tpl = tpl
                return best_tpl

            return {
                "error": f"Unknown GET path: {path}",
                "suggested_template": _best_suggestion(path),
                "known_paths": sorted(list(registry.keys()))[:50],
            }

    allowed_query = get_allowed_query_param_names(effective_path)
    required_path = get_path_param_names(effective_path)

    path_params, query_params = _split_params_for_path(effective_path, effective_params or {})

    missing_path = sorted(list(required_path - set(path_params.keys())))
    if missing_path:
        return {"error": "Missing path parameters", "missing": missing_path, "path": effective_path}

    unknown_query = sorted([k for k in (query_params or {}).keys() if k not in allowed_query])
    if unknown_query:
        return {
            "error": "Unknown query parameters",
            "unknown": unknown_query,
            "allowed": sorted(list(allowed_query)),
            "path": effective_path,
        }

    real_path = _format_path(effective_path, path_params)

    # Make request, mirror uwapi proxy style
    resp = await client.get(real_path, params=query_params, headers=upstream_headers)
    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        try:
            data = resp.json()
            # Derive a simple tool name from the resolved path; fallback to uwmcp
            tool_name = (
                real_path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
                or "uwmcp"
            )
            # Determine content type based on the endpoint path
            lower_path = real_path.lower()
            if "darkpool" in lower_path:
                content_type_ttg = "darkpool_trades"
            elif "options" in lower_path and "chain" not in lower_path:
                content_type_ttg = "options_flow"
            elif "market/movers" in lower_path:
                content_type_ttg = "market_movers"
            else:
                content_type_ttg = "json"

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(data),
                    },
                    {
                        "type": "ttg",
                        "ttg": {
                            "toolName": tool_name,
                            "contentType": content_type_ttg,
                            "data": data,
                        },
                    },
                ]
            }
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

