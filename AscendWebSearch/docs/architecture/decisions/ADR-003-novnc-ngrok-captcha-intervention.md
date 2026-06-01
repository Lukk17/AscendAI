# ADR-003: NoVNC + Ngrok for human CAPTCHA and login-wall intervention

## Status

Accepted — 2026-05-31

## Context

Some pages cannot be accessed without a human solving a CAPTCHA or completing an OAuth login flow. Automated
CAPTCHA solvers handle a subset of challenge types but fail against Cloudflare Turnstile, image-based challenges,
and interactive login flows. Blocking indefinitely or returning empty content without explanation is worse than
surfacing an explicit "human needed" signal.

The service runs as a container, which means a browser process launched inside it is not visible to the operator
by default. The operator needs a way to interact with that browser remotely from their own machine. NoVNC provides
browser access over WebSocket without requiring VNC clients; Ngrok exposes the NoVNC port to the public internet
when the container is behind NAT.

The NoVNC URL changes on every Ngrok tunnel restart. Hardcoding a URL is fragile; the service must be able to
discover the current tunnel URL at runtime.

## Decision

`NoVNCStrategy` (`src/reader/strategies/novnc_strategy.py:81`) raises `HumanInterventionRequiredException` with
the resolved VNC URL. It does not return content. The `human_intervention_exception_handler`
(`src/api/exception_handlers.py:35-48`) maps this to HTTP 428 Precondition Required with body:

```json
{
  "status": "human_intervention_required",
  "intervention_type": "captcha|login",
  "vnc_url": "https://abc123.ngrok.io/vnc.html?autoconnect=true",
  "message": "Manual Captcha resolution required. Please visit: ..."
}
```

The MCP tool docstring (`src/api/mcp/mcp_server.py:40-41`) instructs the agent to display the `vnc_url` to the
user when `status` is `human_intervention_required`. The MCP surface catches
`HumanInterventionRequiredException` explicitly in `web_read` and returns the same structured payload as a tool
result — without that catch, FastMCP marks the call as a generic tool error and the docstring contract is
silently broken.

Before raising, `NoVNCStrategy` spawns a background `asyncio.Task` (`_monitor_for_cookies`,
`src/reader/strategies/novnc_strategy.py:19`) that opens a real Chromium window (headless=False) navigated to
the target URL, polls `context.cookies()` every 5 seconds, and writes the resulting session to `CookieManager`.
The task exits early once the page URL changes away from the challenge page, or after `NOVNC_TIMEOUT_SECONDS`
(default 600 s). A strong reference is held in `_active_monitor_tasks` to prevent GC of the task mid-flight.

VNC URL resolution (`_resolve_public_vnc_url`, `src/reader/strategies/novnc_strategy.py:100-105`) checks whether
`PUBLIC_VNC_URL` contains `api/tunnels`. If it does, it fetches the Ngrok API response and extracts
`tunnels[0].public_url` from the JSON. This handles the case where the tunnel URL changes between restarts.
If the API call fails, it falls back to `SELENIUM_BROWSER_VNC_URL`.

## Alternatives Considered

### Alternative 1: Return empty content and log a warning
- **Pros**: No extra complexity; no 428 status code to handle.
- **Cons**: Silent failure. The caller receives no content and has no way to know whether the page is empty or
  inaccessible. Retrying blindly will loop indefinitely.
- **Why not**: A clear signal is strictly better than silence for any caller that can act on it.

### Alternative 2: Dedicated CAPTCHA-solving service (2captcha, Anti-Captcha)
- **Pros**: Fully automated; no human involvement.
- **Cons**: Per-solve cost. Does not handle login walls, OAuth flows, or interactive challenges. Requires an
  external API key in every environment. Cloudflare Turnstile is not solvable by most token-based solvers.
- **Why not**: Human intervention covers every challenge type that automated solvers miss. The 428 protocol is
  already designed to prompt the user via the agent.

### Alternative 3: Static Ngrok URL configured as an environment variable
- **Pros**: No HTTP call at runtime to resolve the URL.
- **Cons**: Every tunnel restart requires an env-var update and container restart. Free Ngrok plan assigns random
  subdomains per restart; a static URL is only available on paid plans.
- **Why not**: Dynamic URL extraction from `api/tunnels` works for both free and paid plans with no operator
  action after each restart.

## Consequences

### Positive
- Every challenge type is handled via one protocol. The caller does not need to distinguish Cloudflare WAF,
  Turnstile, or login walls.
- Background cookie monitoring persists the session to Redis after the human solves the challenge, so subsequent
  requests to the same domain re-use the clearance without re-triggering NoVNC.
- The 428 body is structured for agent consumption; AscendAgent can display the VNC URL to the user.

### Negative
- NoVNC requires the container to run a visible browser window (headless=False), which needs a display server
  (Xvfb) or the Playwright container image that bundles one. The Docker base image
  (`mcr.microsoft.com/playwright/python:v1.60.0-noble`) provides this.
- The 600-second default timeout means the background task holds a Chromium process open for up to 10 minutes.
  On constrained hosts this is significant memory cost.
- Ngrok API calls introduce a 5-second timeout at the point where the 428 is being generated. If Ngrok is down,
  the fallback URL may not be reachable either.

### Risks
- **Task GC under high concurrency**: The `_active_monitor_tasks` module-level set holds strong references.
  A burst of simultaneous NoVNC triggers could accumulate many live tasks. Each holds a full Chromium context.
  No cap on concurrent tasks exists today.
- **Cookie pollution**: The background task polls every 5 seconds and overwrites any existing session in Redis.
  If the human navigates away during the solve, cookies from an intermediate page may overwrite the correct
  clearance cookie. The early-exit check (`is_login_redirect_url(current_url)`) mitigates but does not
  eliminate this.

### Accepted security posture (call-outs from 2026-05-31 audit)

The audit surfaced three concerns that the operator explicitly accepted rather than mitigated. Documented here
so the next reviewer sees them without re-running the analysis.

- **`vnc_url` is returned plain in the 428 body, with no per-session token.** Anyone who observes the response
  body (logs, MCP transcripts, intermediaries) can connect to the same NoVNC session. The operator runs NoVNC
  on a personal Ngrok tunnel under their own control, accepts the session-takeover risk, and prefers the
  simplicity of an unauthenticated URL over the friction of token gating.
- **Chromium is launched with `--no-sandbox` and `--remote-debugging-port=9222`.** The CDP port is bound to all
  interfaces inside the container, meaning any sibling container on the same Docker network could drive
  Chromium. The operator runs the stack on a single host with no untrusted sibling containers and accepts the
  exposure.
- **The Ngrok tunnel itself has no OAuth or IP allowlist.** Tunnel URLs are randomised per restart but are
  guessable; the same trade-off as the `vnc_url` token applies.

If this service is ever deployed somewhere the operator is not the only user of the host, all three of these
need revisiting. See `code-reviewer` and `security-auditor` reports from 2026-05-31 for the full attack tree.

## Related

- `src/reader/strategies/novnc_strategy.py` — `NoVNCStrategy`, `_monitor_for_cookies`, `_resolve_public_vnc_url`,
  `_fetch_ngrok_url`.
- `src/api/exceptions.py` — `HumanInterventionRequiredException`.
- `src/api/exception_handlers.py:35-48` — 428 handler.
- `src/config/config.py` — `PUBLIC_VNC_URL`, `SELENIUM_BROWSER_VNC_URL`, `SELENIUM_BROWSER_CDP_URL`,
  `NOVNC_TIMEOUT_SECONDS`.
- [ADR-002](ADR-002-cloudflare-cookie-persistence-redis.md) — cookie persistence that makes human solves durable.
