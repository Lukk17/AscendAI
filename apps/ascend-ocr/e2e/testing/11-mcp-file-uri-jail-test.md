# MCP file:// jail: e2e test

## What this verifies

- `ocr_submit` refuses a `file://` URI while `MCP_FILE_URI_ROOT` is unset, which is the default secure posture.
- The refusal carries the `UNSAFE_URI` code.
- No identifier is issued, and nothing is queued: the job listing is empty afterwards.
- When the root is set, a `file://` URI whose path resolves outside that directory (`/tmp/ocr-jail/../../etc/passwd`,
  which `realpath` turns into `/etc/passwd`) is still refused with `UNSAFE_URI`, by the jail rather than by the
  disabled switch, and nothing outside the root is read or queued.

## How the root is set

The development stack runs `ascend-ocr` with `MCP_FILE_URI_ROOT` unset, and `compose.yaml` reads no variable for it,
so the setting cannot be switched on without editing the compose file or restarting the service with a different
environment. Neither is acceptable for one spec. Steps 4 to 9 instead start a second, throwaway container from the
same image, named `ascend-ocr-jail`, with the root set to `/tmp/ocr-jail` and its port bound to `127.0.0.1:7023`. The
suite's own `ascend-ocr` container on port 7022 is never touched, and step 9 removes the throwaway one.

The throwaway container warms its OCR engine at startup like any other, which occupies about one core and roughly a
gigabyte of memory for a minute or so. It reads no document, but it has to be gone before any engine-bound spec of
any suite starts, which step 9 guarantees.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-ocr server is reachable.

```bash
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `"status":"ok"` in the body.

Check nothing is in flight, because step 3 asserts an empty listing.

```bash
curl -fsS http://localhost:7022/ready
```

Expect `"jobs_queued":0` and `"jobs_running":0`. Anything else means an earlier run left work behind: wait for it to
finish or reset per [`../README.md`](../README.md) "Resetting between runs" before starting.

Check the image the throwaway container is started from exists.

```bash
docker image inspect ascend-ai-ascend-ocr:latest --format "{{.Id}}"
```

Expect an image id. If it is missing, `docker compose up -d --build ascend-ocr` builds it.

Check no leftover throwaway container exists, from an earlier run that stopped before its cleanup.

```bash
docker ps -a --filter "name=^ascend-ocr-jail$" --format "{{.Names}}"
```

Expect nothing printed. If `ascend-ocr-jail` is printed, remove it with the command in step 9 first.

Check port 7023 is free.

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:7023/health
```

Expect `000`, meaning nothing answered.

## Reset state

None. The guard refuses every submission before any fetch, so nothing reaches the queue, the jobs directory or the
bucket of either container, and the throwaway container is removed by the spec's own last step.

## Run

Step 1. Open an MCP session on the suite's container and keep the session id. FastMCP answers the `initialize` call
with an `Mcp-Session-Id` response header, and every `tools/call` in this spec carries it back.

```bash
curl -isS -X POST http://localhost:7022/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"1\"}}}"
```

Expect HTTP 200 and an `mcp-session-id` response header. Use that value as the `mcp_session_id` env-var below.

```bash
cd docs/api/request/AscendAI
```

Complete the handshake. The MCP protocol requires the client to send the `notifications/initialized` notification
after `initialize` and before any other request on the session.

```bash
bru run "ocr/testing/mcp-initialized.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Expect HTTP 202 with an empty body.

Step 2. Submit `file:///etc/passwd` to the suite's container, where the root is unset.

```bash
bru run "ocr/testing/mcp-file-uri-disabled.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Step 3. Read the suite's container's listing.

```bash
bru run "ocr/testing/ocr-jobs-list-empty.yml" --env ascend-local
```

Step 4. Start the throwaway container with the root set.

Git Bash on Windows rewrites any argument that looks like a Linux path, `MCP_FILE_URI_ROOT=/tmp/ocr-jail` here and
`/tmp/ocr-jail` in step 5, into a Windows path before Docker sees it. The container then either fails outright
(`mkdir: cannot create directory 'C:'`) or runs with a root the spec never meant. In Git Bash, run the `docker run`
and `docker exec` commands of steps 4 and 5 with `MSYS_NO_PATHCONV=1` set, for example as
`MSYS_NO_PATHCONV=1 docker exec ascend-ocr-jail mkdir -p /tmp/ocr-jail`. PowerShell and Linux or macOS shells need
nothing extra.

```bash
docker run -d --rm --name ascend-ocr-jail -p 127.0.0.1:7023:7022 -e MCP_FILE_URI_ROOT=/tmp/ocr-jail ascend-ai-ascend-ocr:latest
```

Expect a container id printed.

Step 5. Read its liveness, repeating every five seconds for up to 120 seconds until it answers.

```bash
curl -fsS http://localhost:7023/health
```

Then create the root inside it, so the jail guards a directory that exists, as it would in a real deployment.

```bash
docker exec ascend-ocr-jail mkdir -p /tmp/ocr-jail
```

Step 6. Open an MCP session on the throwaway container and keep that session id. It is a different server, so the
session from step 1 is not valid there.

```bash
curl -isS -X POST http://localhost:7023/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"1\"}}}"
```

Complete the handshake on the throwaway container with the step 6 session id.

```bash
bru run "ocr/testing/mcp-initialized-jail.yml" --env ascend-local --env-var "mcp_session_id=<session id from step 6>"
```

Expect HTTP 202 with an empty body.

Step 7. Submit the escape attempt to the throwaway container.

```bash
bru run "ocr/testing/mcp-file-uri-jail-escape.yml" --env ascend-local --env-var "mcp_session_id=<session id from step 6>"
```

Step 8. Read the throwaway container's listing.

```bash
curl -fsS http://localhost:7023/v1/ocr/jobs
```

Step 9. Remove the throwaway container. Run this even when an earlier step failed.

```bash
docker rm -f ascend-ocr-jail
```

Then confirm it is gone.

```bash
docker ps -a --filter "name=^ascend-ocr-jail$" --format "{{.Names}}"
```

## Expected

Step 2:

- HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result.
- The message carries `UNSAFE_URI`.
- No `job_id` anywhere in the answer.

Step 3:

- HTTP 200 with `{"jobs": []}`.

Steps 4 to 6:

- The container starts, `/health` answers HTTP 200 within 120 seconds, the `initialize` call answers HTTP 200
  with an `mcp-session-id` header, and the `notifications/initialized` notification answers HTTP 202.

Step 7:

- HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result.
- The message carries `UNSAFE_URI` and `escapes MCP_FILE_URI_ROOT`, and does not carry `MCP_FILE_URI_ROOT is unset`,
  which proves the root was set and the jail itself refused the path.
- The message carries no line of `/etc/passwd` (no `root:x:0:0`).
- No `job_id` anywhere in the answer.

Step 8:

- `{"jobs":[]}`.

Step 9:

- `docker rm -f` prints `ascend-ocr-jail`, and the confirmation prints nothing.

## Fixtures

None.

## Concurrency

Reject-fast on the suite's container: nothing is queued and the suite's engine is never used. Steps 1 to 3 finish in
well under two seconds. Steps 4 to 9 take as long as the throwaway container needs to come up, typically under a
minute and never more than about two, and its engine warm-up competes for a core while it runs. Safe to run in
parallel with the other reject-fast specs, up to the runner's default cap of five concurrent, because none of them
uses an engine. Never alongside an engine-bound spec of any suite (for this suite 2, 3, 4, 6, 13, 14, 15, 16, 17, 18,
19), and step 9 must have run before the first one starts.
