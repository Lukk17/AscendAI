# MCP credentials-in-URI rejection: e2e test

## What this verifies

The MCP tool rejects URIs containing `userinfo` (e.g. `http://user:pass@host/...`) before any DNS lookup or
HTTP fetch — closes the credential-leakage class flagged in the security audit.

## Prerequisites

```powershell
bru --version
```

```powershell
curl -fsS http://localhost:7022/health
```

## Reset state

None.

## Run

**Step 1.** Open an MCP session per spec 8 and capture `Mcp-Session-Id`.

**Step 2.** Send the credentials probe, writing the run output to a file so the response frame can be read back.

```powershell
bru run "paddle-ocr/testing/mcp-credentials-in-uri.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID>" -o "$env:TEMP\paddle-creds-run.json" -f json
```

**Step 3.** Print the response frame the service sent back.

```powershell
(Get-Content "$env:TEMP\paddle-creds-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data
```

Bruno's console output shows the status and its own test results but never the response body, so step 3 is what
makes the body assertions below checkable.

## Expected

- Step 2 returns HTTP 200 carrying a JSON-RPC error envelope referencing `UNSAFE_URI`.
- The frame printed by step 3 does NOT contain `user:pass`, `pass@`, or the offending URI in any form. The service
  refuses the URI without echoing the submitted credentials back to the caller.

The second assertion replaces an earlier check that grepped `docker logs ascend-paddle-ocr` for `user:pass`. That
check broke the suite's behaviour-only contract, and it could not prove what it claimed: `docker logs` shows only
what is still in the container's current buffer at the moment you run it, so a clean grep is equally consistent
with "the credentials were never written" and with "they were written and the line has since rotated out" or "this
deployment's log level never emitted that line". Response-body content is the leak path a caller can actually
observe, and it is the one this suite can assert on.
