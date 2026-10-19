# Structured extraction: e2e test

## What this verifies

The three deterministic formats of `web-search-structured-extraction` on pages fetched by the real
tiers of the image, with a real browser for the screenshot. No model, web-hunter only.

1. The JSON-LD product page read with `output_format` `structured` answers HTTP 200 with the article
   fields and a `metadata` object holding the product block's canary name and price.
2. The table page read with `output_format` `tables` answers HTTP 200 with the fixture's rows, cell
   for cell.
3. The article read twice with `output_format` `screenshot` and `tier` `4-playwright_stealth` answers
   HTTP 200 both times with a base64 value that decodes to bytes starting with the PNG signature, and
   the request log shows two requests to the article, so the screenshot was not served from the read
   cache.

The malformed JSON-LD page, the `include_links` refusal and the `extraction_not_configured` refusal are
not steps of this spec: the unit tests of tasks 2.1, 5.1 and 3.1 prove them (owner answer 91.3 of
2026-10-08). The three steps kept run the formats on pages fetched by the real tiers of the image,
with a real browser for the screenshot.

## Concurrency

Reads only, opens no NoVNC flow, safe beside every spec.

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

Check the fake site is reachable from the host.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Expect `{"requests":[]}` on a fresh start (any list proves reachability; the reset step below empties it
anyway).

## Reset state

Empty the fake site request log and restore the product page to layout 1 (a previous run of spec 15
switches it to layout 2).

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

Step 1 - JSON-LD product page as structured.

```bash
bru run "web-hunter/testing/extraction/structured-jsonld.yml" --env ascend-local
```

Step 2 - table page as tables.

```bash
bru run "web-hunter/testing/extraction/tables.yml" --env ascend-local
```

Step 3 - article as screenshot, twice, on the pinned Playwright tier.

```bash
bru run "web-hunter/testing/extraction/screenshot.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/extraction/screenshot.yml" --env ascend-local
```

## Expected

- **Step 1:** HTTP 200. Body `content` holds the product sentence, `metadata["json-ld"][0].name`
  equals `"Brassbound Meridian Astrolabe"` and `metadata["json-ld"][0].offers.price` equals `847.25`.
- **Step 2:** HTTP 200. Body `tables` equals, cell for cell,
  `[[["SKU-1147","Cinder Sparrow feeder","23.50"],["SKU-2203","Lumen Badger hutch","89.99"],["SKU-3318","Helix Finch perch","12.75"]]]`.
- **Step 3:** HTTP 200 both times. Body `content` starts with `"iVBOR"` (base64 of the PNG signature).
  The request log then shows exactly two requests to the article, so the second read re-ran the chain
  instead of serving a cached PNG:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/article'))"
  ```

  Expect `2`.

Every assertion above is an HTTP status, a response body or the fake site request log.

## Fixtures

None. The fake site pages `/product`, `/tables` and `/article` carry the canaries (product name and
price, table rows, article survey).
