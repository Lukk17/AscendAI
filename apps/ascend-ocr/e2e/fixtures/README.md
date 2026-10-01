# e2e fixtures

Small canary images used by upload-style OCR tests. Each fixture holds distinctive proper nouns so a passing test
proves the text came from the OCR pipeline rather than memorised knowledge.

## Conventions

- PNG or PDF, high contrast (black text on white background).
- Include rare proper nouns the test asserts against by substring (case-insensitive).
- Keep fixtures < 500 KB so upload completes quickly. The straightening photo set is a deliberate exception, kept at
  full resolution so the service's own shrinking of real phone photos is tested (the owner's decision on 2026-09-25).
- A multi-page fixture puts its canary on a late page, so a spec that finds the canary has proved the whole document
  was read.
- No page is refused for its pixel count. The service renders each PDF page itself at the quality mode's resolution
  ([ADR-010](../../docs/architecture/decisions/ADR-010-quality-modes-and-service-side-rendering.md)), shrinking a
  page whose long side would exceed the mode's largest (2100 px in `normal`, 4200 px in `high`) and never enlarging
  one. A page of 595 by 842 points, which is A4, reaches inference as 2480 x 3509 pixels in `high`, the default, and
  1240 x 1755 in `normal`. The one pixel refusal left is a raster image frame above `OCR_MAX_SOURCE_PIXELS`.

## Per-fixture documentation

| File | Used by | Distinctive content |
| :--- | :--- | :--- |
| `argent-saga-chronicles-page1.png` | `1-invalid-input-test.md`, `2-ocr-english-test.md`, `4-ocr-default-language-test.md`, `6-mcp-ocr-test.md`, `14-job-listing-test.md`, `15-cancel-running-job-test.md`, `16-queue-full-test.md` | Screenshot of page 1 of `apps/ascend-agent/e2e/fixtures/argent-saga-chronicle.pdf`. Tests assert the extracted text contains `Argent Saga`, `Aenaria`, `Halen Veyr` (case-insensitive). |
| `argent-saga-chronicles-page1-polish.png` | `3-ocr-polish-test.md`, `14-job-listing-test.md` | Polish translation of page 1, screenshotted from a text editor. Tests assert the extracted text contains `Saga Świetlna`, `Aenaria`, `Eklipsą`, and at least one Polish-specific accented character. |
| `halcyon-ledger-25-pages.pdf` | `13-long-document-test.md`, `14-job-listing-test.md`, `15-cancel-running-job-test.md`, `16-queue-full-test.md` | Twenty five A4-in-points pages of clean rendered text, 193 KB. Each page names its own number in the heading, and page 24 alone carries the canary `Halcyon Ledger Canary`, so finding it proves the whole document was read rather than the first page or two. |
| `not-an-image.txt` | `12-ocr-unsupported-mime-test.md` | Plain-text file with no image/PDF magic bytes. Proves the magic-byte sniffer (`src/api/mime_sniffer.py`) rejects the upload even when the client lies about `Content-Type`. |
| `straightening-test-page.pdf` | No spec yet | The one-page A4 source of the straightening photo set, 426 KB. See "Straightening photo set" below. |
| `straightening-test-page.txt` | `17-ocr-rotated-photo-test.md`, `18-ocr-straighten-crumpled-photo-test.md` (the canaries are drawn from it) | The expected text of that page, 21 lines, UTF-8 with LF line endings, the title first. |
| `straightening-photo-flat.jpg` | No spec yet | The phone's own upright edit of the same capture as `straightening-photo-rotated-90.jpg`, turned in the phone's editor and saved again, not a separate shot. The baseline the other five are compared with. |
| `straightening-photo-flat-1600px.jpg` | No spec yet | `straightening-photo-flat.jpg` downscaled to 1205 x 1600, JPEG quality 85, 221 KB. |
| `straightening-photo-flat-1000px.jpg` | No spec yet | `straightening-photo-flat.jpg` downscaled to 753 x 1000, JPEG quality 80, 79 KB. |
| `straightening-photo-flat-640px.jpg` | No spec yet | `straightening-photo-flat.jpg` downscaled to 482 x 640, JPEG quality 75, 31 KB. |
| `straightening-photo-rotated-90.jpg` | `17-ocr-rotated-photo-test.md` | The same flat page photographed turned 90 degrees, stored landscape with no orientation tag, so the pixels themselves are turned. |
| `straightening-photo-angled.jpg` | No spec yet | The flat page shot at an angle, so the text carries perspective distortion. |
| `straightening-photo-bent.jpg` | No spec yet | The page with one edge lifted, so the lines near that edge curve. |
| `straightening-photo-crumpled-1.jpg` | `18-ocr-straighten-crumpled-photo-test.md`, `19-ocr-crumpled-photo-default-test.md` | The page crumpled and then flattened by hand, first shot. |
| `straightening-photo-crumpled-2.jpg` | No spec yet | The same crumpled page, second shot. |

## Straightening photo set

Six real phone photos of one printed page, for testing how well the service reads a page that is turned, seen at an
angle, bent or creased. Every photo shows the same page, so each one is scored against the same expected text in
`straightening-test-page.txt` and the flat shot gives the baseline score.

The page is `straightening-test-page.pdf`: a title and twenty lines of Arial on white A4, mixing an invoice with
amounts, dates, an IBAN and serial numbers, Polish and Spanish pangrams with their accented letters, and two English
pangrams. The owner printed it on A4 at 100 percent scale on 2026-09-25 and photographed it the same day with his own
phone.

The photos are JPEG rather than PNG or PDF because that is what a phone produces. They are the full-resolution
originals straight from the owner's Pixel 9 Pro, not downscaled copies. Each is 6144 by 8160 pixels, portrait, except
the rotated one at 8160 by 6144, and they run from 3.4 MiB to 6.6 MiB (3,524,016 to 6,955,324 bytes), so this set is the
one exception to the 500 KB rule above. The flat photo is the phone's own edit of the rotated shot: the same capture
turned upright in the phone's editor and saved again, so the two differ only by the turn and one extra JPEG save.

The three `straightening-photo-flat-<N>px.jpg` files test how well the service reads a low-quality phone photo: each
is the flat photo shrunk with Pillow's LANCZOS filter to a long side of 1600, 1000 or 640 pixels with its aspect ratio
kept, saved as JPEG at quality 85, 80 or 75, and stripped of every APP segment and comment, so it carries no EXIF,
ICC, XMP or JFIF data.

All metadata was removed before the photos were added, location included. As taken, each carried EXIF with GPS
coordinates, the camera make and model, the capture date and an embedded thumbnail, plus XMP, an ICC profile, an MPF
index with an Ultra HDR gain map appended after the main image, APP11 blocks, and on some an IPTC block. Every
orientation tag was 1, so no photo needed turning. Each file was rebuilt from the original's quantisation tables,
frame header, Huffman tables and compressed scan, copied byte for byte and cut at the main image's end marker, and
every APP segment, comment and trailing byte was dropped. Nothing was re-encoded, so each photo decodes to exactly the
pixels the phone saved. With the ICC profile gone, a viewer shows the pixel values as sRGB.

## MCP fixture delivery

Test 6 (the MCP `ocr_submit` call) takes a `file_uri` argument rather than a multipart upload or a container-visible
path. It uses no bind mount. The runner uploads the fixture from the host during the spec's Reset state, with a plain
`PUT` against the object store's S3 endpoint on port 9070, into the `e2e-fixtures` bucket under the key
`argent-saga-chronicles-page1.png`. The bucket is created by the same step and is never deleted by the spec.

Test 6's Bruno request then passes `file_uri="http://host.docker.internal:9070/e2e-fixtures/argent-saga-chronicles-page1.png"`.
ascend-ocr's MCP tool follows that URL back out to the host-published object store and pulls the bytes itself over
HTTP, so the fixture never has to be visible on the container filesystem. This requires the ascend-ocr container's
`MCP_ALLOWED_HOSTS` to include `host.docker.internal`, since the MCP SSRF guard blocks RFC1918 destinations by
default (see [ADR-001](../../docs/architecture/decisions/ADR-001-mcp-file-transport-uri-only.md)).

## How to regenerate

To regenerate `argent-saga-chronicles-page1.png`:

1. Open `apps/ascend-agent/e2e/fixtures/argent-saga-chronicle.pdf` in any PDF viewer.
2. Screenshot page 1 at a comfortable zoom level (>= 100 percent). Save as `argent-saga-chronicles-page1.png`.

For the Polish version: the Polish translation lives in the commit message of the fixture-update commit. Paste it
into a text editor, screenshot at the same zoom, save as `argent-saga-chronicles-page1-polish.png`.

To regenerate `halcyon-ledger-25-pages.pdf`, run this from the repository root through the module's own virtual
environment. It renders twenty five bilevel pages at 595 by 842 pixels, which PIL writes as 595 by 842 point pages,
and places the canary on page 24.

```bash
apps/ascend-ocr/.venv/Scripts/python.exe apps/ascend-ocr/e2e/fixtures/make_halcyon_ledger.py
```

The generator is [`make_halcyon_ledger.py`](make_halcyon_ledger.py) in this directory. It needs a TrueType font on
the host and nothing else.

To regenerate `straightening-test-page.pdf` and `straightening-test-page.txt`, run this from the repository root the
same way. It renders the page at 2480 by 3508 pixels and writes it as a 300 dpi A4 PDF, and it writes the ground
truth from the same list of lines, so the two cannot drift apart. It needs Arial from `C:/Windows/Fonts`, because
that is the font the printed page used.

```bash
apps/ascend-ocr/.venv/Scripts/python.exe apps/ascend-ocr/e2e/fixtures/make_straightening_test_page.py
```

The generator is [`make_straightening_test_page.py`](make_straightening_test_page.py). The photos cannot be
regenerated. Replacing them means printing the page again, photographing it, and stripping the metadata the same way.

To regenerate the three `straightening-photo-flat-<N>px.jpg` copies from `straightening-photo-flat.jpg`, run
[`make_low_resolution_photos.py`](make_low_resolution_photos.py) from the repository root the same way.

```bash
apps/ascend-ocr/.venv/Scripts/python.exe apps/ascend-ocr/e2e/fixtures/make_low_resolution_photos.py
```
