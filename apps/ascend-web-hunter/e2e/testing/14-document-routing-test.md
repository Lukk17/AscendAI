# Document routing: e2e test

## What this verifies

Non-HTML reads routed to the platform services, each against the real service in the full `ascend-ai`
stack (docling-serve, ascend-ocr, ascend-audio-scribe) and no model. It needs the full stack, so it runs
alone in the quarantine lane.

1. A direct read of the fake site canary PDF answers HTTP 200 with Markdown holding the PDF's canary
   sentence.
2. A direct read of the canary PNG answers HTTP 200 with the OCR Markdown holding the image's canary
   word, and the ascend-ocr job list is empty again after the read. That list shows only work that is
   waiting or running, so an empty list means the job ascend-web-hunter submitted has reached a final
   state and nothing is left in the queue. ascend-web-hunter submits the image with `POST /v1/ocr/jobs`,
   polls `GET /v1/ocr/jobs/{job_id}` until the job is final, fetches the result, answers the read, and
   deletes the job in the background with `DELETE /v1/ocr/jobs/{job_id}`. So the record and the stored
   result (the page text) are gone a few seconds after the read, instead of staying on ascend-ocr for
   `OCR_JOB_RETENTION_SECONDS` (default `3600`), and a read of that job answers HTTP 404 with `code`
   `"JOB_NOT_FOUND"`.
3. A direct read of the canary audio clip `files/canary.mp3` (under 60 seconds, holding one invented
   word) answers HTTP 200 with a transcript holding that word.
4. A direct read of `files/oversized.pdf`, whose declared `Content-Length` is above
   `DOCUMENT_MAX_BYTES`, answers HTTP 200 with `routing_error` `file_too_large`, no 428, exactly one
   request log entry for that path, a GET with `bytes_sent` `0`, no open intervention window, and no
   stored session or window result for the fake site.
5. The page `/pdf-link-blocked`, which links a PDF at a fake site path under the blocked name
   `e2e-fake-site-blocked`, answers HTTP 200 with the page's own text and a `routing_error`, and the
   request log holds exactly one `/files/canary.pdf` entry, the one from Call 1.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check the three routing targets are reachable from the host: docling-serve, ascend-ocr and
ascend-audio-scribe all answer their health endpoint.

```bash
curl -fsS http://127.0.0.1:5001/health
```

```bash
curl -fsS http://127.0.0.1:7022/health
```

```bash
curl -fsS http://127.0.0.1:7017/health
```

Expect HTTP 200 from each. docling-serve answers exactly `{"status":"ok"}`, and ascend-ocr and ascend-audio-scribe
answer `status` `ok` with `service` naming the service and a non-empty `version`.

Check the fake site is reachable from the host.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Expect a request list (empty on a fresh start; the reset step below empties it anyway).

## Reset state

Empty the fake site request log.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

Empty the service's in-process read cache for the fake site. It keeps a read for `READ_CACHE_TTL_SECONDS`
(300 s) and Redis cannot reach it, so without this step a repeat of this spec inside 300 s is answered from
the cache and never reaches docling-serve, ascend-ocr, ascend-audio-scribe or the request log. All five calls
read one registrable domain, so one call clears them. The call also deletes `session:e2e-fake-site:default`
if one exists.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Expect HTTP 200 with `status` `"cleared"`. `cleared_cache_entries` is the number of cached reads removed.

Delete the stored session and the window result of the fake site, because Call 4 checks that neither
exists and an earlier run may have left them, and its remembered tier, because Call 5 writes it. A window
result is kept about 14 days and `session/clear` does not remove it. The command is identical in PowerShell
and Unix shells.

```bash
docker exec redis redis-cli DEL "session:e2e-fake-site:default" "novnc_window_result:e2e-fake-site:default" "tier_memory:e2e-fake-site"
```

Expect a number from `0` to `3`, the count of keys that existed.

Check that the ascend-ocr queue is empty, so no other work is waiting or running while Call 2 reads.

```bash
curl -fsS http://127.0.0.1:7022/v1/ocr/jobs | python3 -c "import json,sys; print(len(json.load(sys.stdin)['jobs']))"
```

Expect `0`. Any other number means another run is using ascend-ocr, which this spec must not share, so
stop and wait until the queue is empty. `GET /v1/ocr/jobs` lists only waiting and running work, so it
cannot show finished jobs of an earlier run, and this spec cannot delete them from here. They do not
affect this run, because no check counts finished jobs, and ascend-ocr removes them after
`OCR_JOB_RETENTION_SECONDS`.

## Run

Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

Call 1 - direct read of the canary PDF.

```bash
bru run "web-hunter/testing/extraction/route-pdf.yml" --env ascend-local
```

Call 2 - direct read of the canary PNG.

```bash
bru run "web-hunter/testing/extraction/route-image.yml" --env ascend-local
```

Call 3 - direct read of the canary audio clip.

```bash
bru run "web-hunter/testing/extraction/route-audio.yml" --env ascend-local
```

Call 4 - direct read of the oversized PDF.

```bash
bru run "web-hunter/testing/extraction/route-pdf-oversized.yml" --env ascend-local
```

Call 5 - page linking a PDF under the blocked name.

```bash
bru run "web-hunter/testing/extraction/route-private-link.yml" --env ascend-local
```

## Expected

- **Call 1:** HTTP 200. Body `content` holds `"HELIX-FINCH"`, the canary sentence of `canary.pdf`.
- **Call 2:** HTTP 200. Body `content` holds `"Mirellion"`, the canary word of `canary.png`. The
  ascend-ocr queue is then empty again:

  ```bash
  curl -fsS http://127.0.0.1:7022/v1/ocr/jobs | python3 -c "import json,sys; print(len(json.load(sys.stdin)['jobs']))"
  ```

  Expect `0`. The list shows only waiting and running work, so `0` means the job Call 2 submitted is in
  a final state and nothing is left in the queue. The list cannot show that the job was deleted, so
  read the job itself. ascend-web-hunter keeps no record of the job identifier and does not put it in
  the read's answer, so the identifier comes from the line ascend-ocr logs when a job changes state:
  `Job <job_id> -> succeeded (pages=1, reason=-)`. This log read only finds the identifier. It is not a
  pass criterion. Replace `<Start (UTC)>` with the start time recorded in the run file, written like
  `2026-11-08T10:15:00Z`. The spec runs alone in the quarantine lane, so the only job that succeeded
  since then is the one of Call 2.

  PowerShell:

  ```powershell
  docker logs ascend-ocr --since "<Start (UTC)>" 2>&1 | Select-String -SimpleMatch -Pattern "-> succeeded"
  ```

  Unix:

  ```bash
  docker logs ascend-ocr --since "<Start (UTC)>" 2>&1 | grep -F -- "-> succeeded"
  ```

  Expect one line. The word after `Job` is the job identifier. ascend-web-hunter deletes the job in the
  background after the read answers, so give the delete time first. Poll the job once a second until it
  answers HTTP 404, for at most 10 tries.

  PowerShell:

  ```powershell
  for ($i = 0; $i -lt 10; $i++) { $code = curl.exe -sS -o NUL -w "%{http_code}" http://127.0.0.1:7022/v1/ocr/jobs/<job_id>; if ($code -eq "404") { break }; Start-Sleep -Seconds 1 }
  ```

  Unix:

  ```bash
  for i in $(seq 1 10); do code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:7022/v1/ocr/jobs/<job_id>); [ "$code" = "404" ] && break; sleep 1; done
  ```

  The poll only waits. It is not a pass criterion. Read the job.

  ```bash
  curl -sS http://127.0.0.1:7022/v1/ocr/jobs/<job_id>
  ```

  Expect HTTP 404 with `code` `"JOB_NOT_FOUND"`, because ascend-web-hunter deleted the job in the
  background after the read. HTTP 200 with `state` `succeeded` after the poll means the job and its
  stored result were left on ascend-ocr, and Call 2 fails. No line in the log means Call 2 never got a finished job, and Call 2 fails too.
- **Call 3:** HTTP 200. Body `content` holds `"KAKSMA"` or `"Kaxma"` (case-insensitive match), the invented word the `canary.mp3` clip speaks
  once (CPU transcribes `KAKSMA`, GPU transcribes `Kaxma.` via whisper-large-v3; recorded in [fixtures/README.md](../fixtures/README.md) as Kaksma).
- **Call 4:** HTTP 200 with `routing_error` equal to `"file_too_large"`, and no 428. The request log
  holds exactly one entry for the oversized path, a GET with no body bytes sent:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=[r for r in json.load(sys.stdin)['requests'] if r['path']=='/files/oversized.pdf']; print([(r['method'], r['bytes_sent']) for r in rs])"
  ```

  Expect exactly `[('GET', 0)]`. Then check that no intervention window is open.

  ```bash
  curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
  ```

  Expect `active_flows` `0`. Then check that no session and no window result was stored for the fake
  site. The command is identical in PowerShell and Unix shells.

  ```bash
  docker exec redis redis-cli EXISTS "session:e2e-fake-site:default" "novnc_window_result:e2e-fake-site:default"
  ```

  Expect `0`.
- **Call 5:** HTTP 200. Body `content` holds `"HALCYON-PLOVER"`, the page's own canary sentence, plus a
  `routing_error` field. The page links `http://e2e-fake-site-blocked:7031/files/canary.pdf`, the same
  path Call 1 read. The request log stores only the path, so a fetch of that link would show as a second
  `/files/canary.pdf` entry:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sorted(r['path'] for r in rs))"
  ```

  Expect the list to hold `/pdf-link-blocked` and exactly one `/files/canary.pdf` entry, the one from
  Call 1.

Every assertion above is an HTTP status, a response body, the OCR job list, the read of the OCR job of
Call 2, the fake site request log, the intervention listing of Call 4 or the Redis keys of Call 4. The
ascend-ocr log only finds the job identifier and is never checked itself.

## Post-run cleanup

Empty the fake site request log.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

Delete the stored session, the window result and the remembered tier of the fake site. The command is
identical in PowerShell and Unix shells.

```bash
docker exec redis redis-cli DEL "session:e2e-fake-site:default" "novnc_window_result:e2e-fake-site:default" "tier_memory:e2e-fake-site"
```

Expect a number from `0` to `3`, the count of keys that existed.

## Fixtures

`fixtures/README.md` canary rows for `files/canary.pdf`, `files/canary.png`, `files/canary.mp3` and
`files/oversized.pdf`, and the `/pdf-link-blocked` page row.

## Concurrency

Step 2 is OCR engine-bound and step 1 is docling-bound, so the whole spec runs alone in the quarantine
lane of `docs/E2E_RUN_SCENARIOS.md`.

- Serial: true. Runs alone in the quarantine lane.
