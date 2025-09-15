UWMCP (MCP server for Unusual Whales)

Overview

- Streamable‑HTTP MCP server exposing a minimal, agent‑friendly toolset for Unusual Whales APIs
- Tools (registered):
  - search_endpoints
  - get_available_params
  - call_get

Environment

- Copy .env.example to .env at the repo root and set as needed:
  - UW_BASE_URL (e.g., https://api.unusualwhales.com or your proxy URL)
  - UW_API_KEY (optional; adds X-API-Key)
  - UW_BEARER_TOKEN (optional; adds Authorization: Bearer …)

Auth header behavior (from uwmcp/auth.py):
```
if UW_API_KEY: headers["X-API-Key"] = UW_API_KEY
if UW_BEARER_TOKEN: headers["Authorization"] = f"Bearer {UW_BEARER_TOKEN}"
```

Deploy to Render (recommended)

1) Create a “Web Service” in Render and point it at this repo/branch
2) Configure service:
   - Build Command: `pip install -r uwmcp/requirements.txt`
   - Start Command: `python -m uwmcp.run_http`
   - Runtime: Python 3.11+ (Render’s default is fine)
3) Environment Variables (Render → Environment):
   - `UW_BASE_URL` = your upstream UW API or proxy URL
   - `UW_API_KEY` = your key (optional)
   - `UW_BEARER_TOKEN` = your bearer token (optional)
   - Do NOT set `PORT` — Render provides it and the server reads it automatically
4) Deploy. The MCP endpoint will be available at:
   - `https://<your-service>.onrender.com/mcp`

Verify

```
curl -i https://<your-service>.onrender.com/mcp
# Expect HTTP/1.1 200 OK
```

Local Run (HTTP transport)

From repo root:
```
python -m uwmcp.run_http
```
This binds 0.0.0.0:${PORT} (defaults to 8000) using streamable‑http.

Tooling Flow (for agents)

1) `search_endpoints` → discover GET endpoints
2) `get_available_params(path)` → allowed path/query params with shallow schemas
3) `call_get(path, params[, headers])` → execute request

Internals

- Single `httpx.AsyncClient` with `Limits(max_connections=1, max_keepalive_connections=1)`, timeout 30s
- OpenAPI loaded from `uwmcp/openapi.yaml`
- Shallow OpenAPI registry (no deep `$ref` expansion), parameter/name validation before calls
- No response caching; direct upstream requests on each call


