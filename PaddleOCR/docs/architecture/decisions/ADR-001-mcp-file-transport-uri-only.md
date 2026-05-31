# ADR-001: MCP file transport — URI-only with SSRF guard and `file://` jail

## Status

Accepted — 2026-05-31

## Context

The MCP `ocr_process` tool accepts an arbitrary source for the bytes to OCR. The Model Context Protocol's JSON-RPC envelope has no native binary payload — every file must be delivered as either a URI the server can fetch, or an inline base64 blob. The choice has cost-of-error consequences: an unbounded URI fetch is a classic SSRF surface, and inline base64 inflates the JSON-RPC frame by ~33 % and is bounded by the wire-level max frame size.

The first cut of the tool accepted a server-local `file_path`. That was rejected because it pushes the operator into mounting fixture directories into the container — a workflow inconsistent with how the rest of the stack moves bytes (REST multipart uploads for the agent's RAG, signed URLs for AscendAgent attachments). It was also a path-traversal vulnerability: any caller able to invoke the tool could OCR `/etc/passwd`, `/run/secrets/*`, mounted volumes.

## Decision

The MCP tool accepts `file_uri: str` and supports two schemes only:

- **`http://` / `https://`** — primary path. The server fetches the bytes via a module-level `aiohttp.ClientSession` opened in the FastMCP lifespan, with a configurable total timeout, `allow_redirects=False`, and the SSRF guard described below.
- **`file://`** — secondary path. Disabled by default. When `MCP_FILE_URI_ROOT` is set, the URI's path is resolved against that root via `os.path.realpath`; any path that escapes the root is rejected. Operators who want to use `file://` must mount a writable directory into the container and configure `MCP_FILE_URI_ROOT` to it. The tool will not invent an upload endpoint; populating the root is an out-of-band operator responsibility.

Bare paths (no scheme), `ftp://`, `data:`, and every other scheme are rejected with `UnsafeUriError`.

### SSRF guard for `http(s)://`

For each request:

1. The hostname is parsed from the URI.
2. If the hostname is listed in `MCP_ALLOWED_HOSTS` (configured allowlist of trusted internal hostnames — typically the docker-internal `minio` hostname), the request is allowed without further checks.
3. Otherwise, the hostname is resolved via `asyncio.get_running_loop().getaddrinfo(...)` and **every** resolved address is checked against `ipaddress.ip_address(...).is_private | is_loopback | is_link_local | is_multicast | is_reserved | is_unspecified`. Any match raises `UnsafeUriError`.
4. URIs containing credentials in `userinfo` are rejected outright.
5. `Content-Length` is checked against `MAX_FILE_SIZE_MB` before reading; the body is streamed with `iter_chunked` and a running byte-count, aborting if the cap is exceeded mid-stream.
6. `allow_redirects=False` is set on the session — a `302 Location: http://169.254.169.254/...` cannot bypass the guard via redirection.

### Base64 deferred

Inline base64 is **not** accepted today. If a future non-MinIO caller needs to push bytes without going through the URI path, a second optional argument (`inline_b64`) can be added with its own size cap (≤ `MAX_FILE_SIZE_MB / 2` to leave headroom for the surrounding JSON-RPC envelope). Adding it now would double the input surface for zero present demand.

## Consequences

### Why this shape

- **Defense in depth.** The IP block alone is too coarse: in a docker network, `minio:9000` resolves to RFC1918 and would be blocked. The IP block alone is too narrow: a public hostname behind DNS rebinding can resolve to `127.0.0.1` between two calls. Combining a small explicit allowlist (`MCP_ALLOWED_HOSTS=minio`) with the IP block gives both predictable internal use and safe external fetches.
- **Default-safe `file://`.** `MCP_FILE_URI_ROOT` defaults to unset, so a fresh deployment cannot read arbitrary container files even if `file_uri="file:///etc/passwd"` is sent. Opting in requires an operator action.
- **No new upload endpoint.** The REST `/v1/ocr` endpoint already accepts multipart uploads; agents that need direct upload semantics use that. `file://` exists for the case where the agent and PaddleOCR share a volume (e.g., a Kubernetes pod with an emptyDir).

### Trade-offs

- **`MCP_ALLOWED_HOSTS=minio` is required to run the e2e tests** that fetch fixtures from the docker-internal MinIO. The e2e test 6 spec documents this explicitly under Prerequisites.
- **DNS TOCTOU.** Between `_validate_host` and aiohttp's own resolve, an attacker controlling the DNS answer can flip from a public IP to a private one. Acceptable trade-off for now; production hardening would add a custom aiohttp resolver that caches the validated address.
- **No content sniffing yet.** A 200 OK with `Content-Type: image/png` and a body that is actually a zip bomb still reaches PaddleOCR. Future hardening: magic-byte sniffing via `python-magic` before invoking the OCR engine.

### Alternatives considered

- **Strict host allowlist only (no IP block).** Rejected. Operationally fragile — every new MinIO bucket / new internal storage host requires a config push. Doesn't help when a host on the allowlist is itself compromised and pointed at an internal address.
- **Block private IPs only (no allowlist).** Rejected for blocking the docker-internal MinIO use case which the rest of the stack already depends on.
- **Drop `file://` entirely.** Rejected. There are legitimate operator workflows (shared volume between agent and PaddleOCR pods, manual debugging from a host shell into the container) where `file://` jailed to a known root is the simplest answer.

## Related

- `PaddleOCR/src/api/mcp/mcp_server.py` — `ocr_process`, `_fetch_file`, `_read_jailed_file`, `_download_http`, `_validate_host`, `_is_blocked`, `_is_within`.
- `PaddleOCR/src/config/config.py` — `MCP_FILE_URI_ROOT`, `MCP_ALLOWED_HOSTS`, `MCP_DOWNLOAD_TIMEOUT_SECONDS`.
- `PaddleOCR/e2e/testing/6-mcp-ocr-test.md` — operator-facing test that exercises this path; requires `MCP_ALLOWED_HOSTS=minio`.
- ADR-M002 (monorepo) — MCP as the standard tool-services protocol.
