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

1) Create a new “Web Service”
   - Dashboard → New → Web Service
   - Connect your GitHub and select this repository/branch
   - Name: any (e.g., `uwmcp`)

2) Environment
   - Runtime: Python 3.11+ (Render default works)
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python run_http.py`
   - Instance Type/Region: choose as needed

3) Environment Variables (Render → Environment)
   - `UW_BASE_URL` = your upstream UW API or proxy URL
   - `UW_API_KEY` = optional; sends `X-API-Key` upstream
   - `UW_BEARER_TOKEN` = optional; sends `Authorization: Bearer ...` upstream
   - `UW_TIMEOUT_SECONDS` = optional; default `30.0`
   - Do NOT set `PORT` — Render injects it, and the server reads it automatically

4) Deploy
   - Click Create Web Service
   - On first build, logs will show Python installing deps and the server starting
   - After deploy, open the service URL in a browser to verify it’s responding

Verify

```
# From your machine (replace with your service URL)
curl -i https://<your-service>.onrender.com
```

Local Run (HTTP transport)

From repo root (package directory), either of the following works:
```
# Option A: script mode (works anywhere)
python run_http.py

# Option B: module mode (run from the parent directory of this folder)
python -m uwmcp.run_http
```
The server binds 0.0.0.0:${PORT} (defaults to 8000) using streamable‑http.

Tooling Flow (for agents)

1) `search_endpoints` → discover GET endpoints
2) `get_available_params(path)` → allowed path/query params with shallow schemas
3) `call_get(path, params[, headers])` → execute request

Internals

- Single `httpx.AsyncClient` with `Limits(max_connections=1, max_keepalive_connections=1)`, timeout 30s
- OpenAPI loaded from `uwmcp/openapi.yaml`
- Shallow OpenAPI registry (no deep `$ref` expansion), parameter/name validation before calls
- No response caching; direct upstream requests on each call


