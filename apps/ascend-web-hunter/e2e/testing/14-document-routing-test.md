# Document routing: e2e test

## What this verifies

Non-HTML reads routed to the platform services, each against the real service in the full `ascend-ai`
stack (docling-serve, ascend-ocr, ascend-audio-scribe) and no model. It needs the full stack, so it runs
alone in the quarantine lane.

1. A direct read of the fake site canary PDF answers HTTP 200 with Markdown holding the PDF's canary
   sentence.
2. A direct read of the canary PNG answers HTTP 200 with the OCR Markdown holding the image's canary
   word, and the finished job is then absent from the ascend-ocr job list (it lists only queued and
   running work by design).
3. A direct read of the canary audio clip `files/canary.mp3` (under 60 seconds, holding one invented
   word) answers HTTP 200 with a transcript holding that word.
4. A direct read of `files/oversized.pdf`, whose declared `Content-Length` is above
   `DOCUMENT_MAX_BYTES`, answers HTTP 200 with a `routing_error` field, and the request log shows no
   body bytes sent for it.
5. The page `/pdf-link-blocked`, which links a PDF at a fake site path under the blocked name
   `e2e-fake-site-blocked`, answers HTTP 200 with the page's own text and a `routing_error`, and the
   request log shows no request to the private path.

## Concurrency

Step 2 is OCR engine-bound and step 1 is docling-bound, so the whole spec runs alone in the quarantine
lane of `docs/E2E_RUN_SCENARIOS.md`.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check the three routing targets are reachable from the host: docling-serve, ascend-ocr and
ascend-audio-scribe all answer their health endpoint.

```bash
curl -fsS http://localhost:5001/health
```

```bash
curl -fsS http://localhost:7022/health
```

```bash
curl -fsS http://localhost:7017/health
```

Expect HTTP 200 with `{"status":"ok"}` from each.

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

Delete the OCR jobs this spec created on a previous run, if any. List the jobs, then delete each one;
deleting a job also forgets its stored result object.

```bash
curl -fsS http://localhost:7022/v1/ocr/jobs
```

For every `job_id` in the `jobs` array:

```bash
curl -fsS -X DELETE http://localhost:7022/v1/ocr/jobs/<job_id>
```

Expect HTTP 204 for each.

## Run

Move into the Bruno collection root first.

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
  finished job is then absent from the ascend-ocr job list:

  ```bash
  curl -fsS http://localhost:7022/v1/ocr/jobs | python3 -c "import json,sys; print(sorted(j['state'] for j in json.load(sys.stdin)['jobs']))"
  ```

  Expect the printed list to hold no `"succeeded"`: finished work is not listed, `GET /v1/ocr/jobs`
  lists only queued and running work by design.
- **Call 3:** HTTP 200. Body `content` holds `"KAKSMA"` or `"Kaxma"` (case-insensitive match), the invented word the `canary.mp3` clip speaks
  once (CPU transcribes `KAKSMA`, GPU transcribes `Kaxma.` via whisper-large-v3; recorded in [fixtures/README.md](../fixtures/README.md) as Kaksma).
- **Call 4:** HTTP 200 with a `routing_error` field. The request log shows the oversized path was
  requested but no body bytes were sent for it:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=[r for r in json.load(sys.stdin)['requests'] if r['path']=='/files/oversized.pdf']; print([(r['method'], r['bytes_sent']) for r in rs])"
  ```

  Expect one entry with `bytes_sent` equal to `0`.
- **Call 5:** HTTP 200. Body `content` holds `"HALCYON-PLOVER"`, the page's own canary sentence, plus a
  `routing_error` field. The request log shows no request to the private path:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sorted(set(r['path'] for r in rs)))"
  ```

  Expect the list to hold `/pdf-link-blocked` and no path containing `e2e-fake-site-blocked`.

Every assertion above is an HTTP status, a response body, the OCR job list or the fake site request log.

## Fixtures

`fixtures/README.md` canary rows for `files/canary.pdf`, `files/canary.png`, `files/canary.mp3` and
`files/oversized.pdf`, and the `/pdf-link-blocked` page row.
