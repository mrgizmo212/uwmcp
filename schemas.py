from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml


def load_spec() -> Dict[str, Any]:
    """Load uwmcp/openapi.yaml (local file only; no fallback)."""
    base_dir = Path(__file__).resolve().parent
    spec_path = base_dir / "openapi.yaml"
    with spec_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_ref(spec: Dict[str, Any], ref: str) -> Optional[Dict[str, Any]]:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node: Any = spec
    for part in ref[2:].split("/"):
        node = node.get(part)
        if node is None:
            return None
    return node


def deep_resolve(spec: Dict[str, Any], obj: Any) -> Any:
    """Inline $ref recursively, matching uwapi/routers/meta.py approach."""
    if isinstance(obj, dict):
        if "$ref" in obj:
            resolved = resolve_ref(spec, obj["$ref"]) or {}
            merged: Dict[str, Any] = {}
            merged.update(deep_resolve(spec, resolved))
            for k, v in obj.items():
                if k == "$ref":
                    continue
                merged[k] = deep_resolve(spec, v)
            return merged
        return {k: deep_resolve(spec, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_resolve(spec, v) for v in obj]
    return obj


def list_paths(spec: Dict[str, Any]) -> List[str]:
    paths = spec.get("paths", {}) or {}
    return list(paths.keys())


def get_operation(spec: Dict[str, Any], path: str, method: str = "get") -> Dict[str, Any]:
    item = (spec.get("paths", {}) or {}).get(path) or {}
    return item.get(method.lower(), {}) or {}


def inline_parameters(spec: Dict[str, Any], op: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = op.get("parameters", [])
    inlined: List[Dict[str, Any]] = []
    for p in params:
        if "$ref" in p:
            p = resolve_ref(spec, p["$ref"]) or {}
        if isinstance(p, dict) and "schema" in p:
            p = {**p, "schema": deep_resolve(spec, p.get("schema"))}
        inlined.append(deep_resolve(spec, p))
    return inlined


def extract_response_schema(spec: Dict[str, Any], op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    responses = op.get("responses", {}) or {}
    ok = responses.get("200") or responses.get(200)
    if not ok:
        return None
    content = ok.get("content", {})
    app_json = content.get("application/json") or {}
    schema = app_json.get("schema") or {}
    return deep_resolve(spec, schema) if schema else None



# --------------------------
# Shallow extractors/registry
# --------------------------

_SHALLOW_REGISTRY: Optional[Dict[str, Any]] = None


def _simplify_schema(spec: Dict[str, Any], schema: Any) -> Any:
    """Return a shallow summary of a schema without deep recursion.

    - Resolves a single level of $ref if present
    - Keeps only simple informative keys: type, format, enum, title, items (shallow)
    - Avoids descending into nested object properties
    """
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        resolved = resolve_ref(spec, schema["$ref"]) or {}
        return _simplify_schema(spec, resolved)
    summary: Dict[str, Any] = {}
    for key in ("type", "format", "enum", "title"):
        if key in schema:
            summary[key] = schema[key]
    if "items" in schema:
        items = schema["items"]
        if isinstance(items, dict) and "$ref" in items:
            resolved_items = resolve_ref(spec, items["$ref"]) or {}
            summary["items"] = _simplify_schema(spec, resolved_items)
        elif isinstance(items, dict):
            summary["items"] = {k: items[k] for k in ("type", "format", "enum", "title") if k in items}
        else:
            summary["items"] = items
    return summary


def get_parameters_shallow(spec: Dict[str, Any], op: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Inline parameters one level only and simplify their schemas without deep recursion."""
    params = op.get("parameters", []) or []
    inlined: List[Dict[str, Any]] = []
    for p in params:
        if "$ref" in p:
            p = resolve_ref(spec, p["$ref"]) or {}
        if not isinstance(p, dict):
            continue
        simple: Dict[str, Any] = {
            "name": p.get("name"),
            "in": p.get("in"),
            "required": p.get("required", False),
        }
        if "schema" in p:
            simple["schema"] = _simplify_schema(spec, p.get("schema"))
        inlined.append(simple)
    return inlined


def extract_response_schema_shallow(spec: Dict[str, Any], op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a shallow response schema summary (no deep recursion)."""
    responses = op.get("responses", {}) or {}
    ok = responses.get("200") or responses.get(200) or responses.get("default")
    if not ok:
        return None
    content = ok.get("content", {}) or {}
    app_json = content.get("application/json") or {}
    schema = app_json.get("schema") or {}
    return _simplify_schema(spec, schema) if schema else None


def _path_param_names(path_template: str) -> Set[str]:
    import re

    return set(re.findall(r"\{([^/}]+)\}", path_template))


def build_registry_shallow(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Build a shallow, cached registry of GET endpoints and their parameter metadata."""
    registry: Dict[str, Any] = {}
    for path in list_paths(spec):
        op = get_operation(spec, path, method="get")
        if not op:
            continue
        summary = op.get("summary") or op.get("description") or ""
        tags = op.get("tags") or []
        parameters = get_parameters_shallow(spec, op)
        response_schema = extract_response_schema_shallow(spec, op)
        registry[path] = {
            "summary": summary,
            "tags": tags,
            "parameters": parameters,
            "pathParamNames": sorted(list(_path_param_names(path))),
            "queryParamNames": sorted([p.get("name") for p in parameters if p.get("in") == "query" and p.get("name")]),
            "responseSchema": response_schema,
        }
    return registry


def get_registry_shallow() -> Dict[str, Any]:
    global _SHALLOW_REGISTRY
    if _SHALLOW_REGISTRY is None:
        spec = load_spec()
        _SHALLOW_REGISTRY = build_registry_shallow(spec)
    return _SHALLOW_REGISTRY


def get_allowed_query_param_names(path: str) -> Set[str]:
    reg = get_registry_shallow()
    entry = reg.get(path) or {}
    return set(entry.get("queryParamNames", []) or [])


def get_path_param_names(path: str) -> Set[str]:
    reg = get_registry_shallow()
    entry = reg.get(path)
    if entry and "pathParamNames" in entry:
        return set(entry["pathParamNames"])
    return _path_param_names(path)

