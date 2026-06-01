# ADR-001: URI-only MCP transport with SSRF + file:// jail

**Date**: 2026-06-01
**Status**: Accepted
**Deciders**: Łukasz Sarna

---

## Context

The MCP surface accepts `audio_uri` instead of multipart uploads (MCP clients are server-to-server and have no
multipart story). Without explicit guards the URI fetcher reaches arbitrary network targets and arbitrary local
files: an attacker can probe internal network topology via `http://169.254.169.254/...` (AWS IMDS), read internal
service URLs (`http://qdrant:6333/`, `http://redis:6379/`), or read host secrets via `file:///etc/passwd`,
`file:///proc/self/environ`. This is exactly the attack model PaddleOCR's ADR-001 fixed for its OCR fetcher.

---

## Decision

The MCP `audio_uri` parameter only accepts two schemes, each guarded:

1. `http(s)://` — `_validate_http_target` resolves the hostname via `socket.getaddrinfo` and rejects any IP that
   matches `ipaddress.ip_address(...).is_private | is_loopback | is_link_local | is_multicast | is_reserved |
   is_unspecified`. Hostnames listed in `MCP_ALLOWED_HOSTS` bypass the check (for the docker-internal MinIO pattern).
   Unresolvable hostnames are rejected. The download path streams with `MAX_DOWNLOAD_BYTES` enforcement.
2. `file://` — disabled by default. Requires `MCP_FILE_URI_ROOT` to be set; URIs are resolved under the root via
   `pathlib.Path.resolve()` and rejected if `is_relative_to(root)` is False (catches `..` traversal even with
   symlinks).

All other schemes (`ftp`, `data:`, bare paths, Windows drive letters) are rejected with a `ValueError` that maps to
an MCP `validation_error` envelope. (`src/adapters/download_service.py`)

---

## Alternatives Considered

### Alternative 1: Accept any URI; trust upstream callers

- **Pros**: Simplest.
- **Cons**: Cloud metadata is reachable from any compromised caller. Internal services exposed.
- **Why not**: Single shared MCP gateway means any compromised tool exposes the whole platform.

### Alternative 2: Allow file:// freely; rely on filesystem permissions

- **Pros**: No env-var to set.
- **Cons**: The container's `appuser` can still read `/etc/passwd`, `/proc/self/environ`, mounted docker secrets.
- **Why not**: Permissions aren't a substitute for explicit path validation.

---

## Consequences

### Positive

- SSRF surface eliminated for the MCP path. Cloud metadata, internal services, and link-local addresses are blocked.
- `file://` requires an explicit opt-in via env var; production deployments without that var get a clean rejection.
- Same model as the sibling PaddleOCR service; ops staff only learn one pattern.

### Negative

- Adds two env vars (`MCP_FILE_URI_ROOT`, `MCP_ALLOWED_HOSTS`) operators must understand. Documented in
  `docs/CONFIGURATION.md`.
- DNS resolution adds latency to every HTTP MCP call; with 1-2 ms cache hits this is acceptable.

### Risks

- **DNS rebinding**: a hostname that initially resolves to a public IP could re-resolve to a private one between the
  guard check and the aiohttp connect. Mitigation: aiohttp itself resolves at connect time. Defense in depth would
  pin the resolved IP and pass it to `aiohttp.ClientSession.get(headers={"Host": hostname})`; not yet implemented.
