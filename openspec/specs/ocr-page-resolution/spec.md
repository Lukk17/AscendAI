# ocr-page-resolution Specification

## Purpose
Decides how the service turns a submitted document into the page images its engine reads: the resolution each page
is rendered at, the quality mode a caller picks, how an oversized page is shrunk rather than refused, and how long one
page may take, so that read quality is a choice the request makes rather than a value the OCR library fixed.

## Requirements

### Requirement: The service renders every page itself, one at a time, at the resolution the request asks for

The service SHALL turn every submitted document into page images itself, and SHALL hand the OCR engine one page image
at a time. A PDF page SHALL be rendered at the resolution the request's quality mode names. A raster image SHALL be
decoded by the service. The resolution a page is read at SHALL NOT be fixed for the life of the process, and SHALL NOT
be decided by the OCR library's own rasterizer. The per-page deadline SHALL be checked before each page is produced.

#### Scenario: Two requests in one process read the same PDF at different resolutions

- **WHEN** the same PDF is submitted once in `normal` mode and once in `high` mode to one running service
- **THEN** its pages are rendered at 150 dpi for the first request and at 300 dpi for the second

#### Scenario: The deadline expires between pages

- **WHEN** a document's reading budget expires after one page has been read
- **THEN** the next page is neither rendered nor read
- **AND** the work fails with the existing OCR failure code

#### Scenario: A multi-page TIFF is read and counted as its pages

- **WHEN** a TIFF holding three frames is submitted
- **THEN** the submission reports three pages
- **AND** each frame is read as its own page

### Requirement: A caller chooses a quality mode, and each mode is a locked pair

Job submission SHALL accept an optional `quality` parameter on both surfaces, with exactly the values `normal` and
`high`. Each mode SHALL name one render resolution and one detector input bound together, and a caller SHALL NOT be
able to supply either number. When `quality` is omitted the mode SHALL be `high`. A value other than the two SHALL be
refused before any work is queued. The mode a document was read in SHALL be reported with its result.

#### Scenario: Shipped pairs

- **WHEN** the service starts with no quality settings supplied
- **THEN** `normal` renders at 150 dpi and bounds detection to a long side of 1024
- **AND** `high` renders at 300 dpi and bounds detection to a long side of 1536

#### Scenario: Omitted quality

- **WHEN** a document is submitted without a `quality` value on either surface
- **THEN** it is read in `high` mode
- **AND** its result reports `high`

#### Scenario: Unknown quality

- **WHEN** a document is submitted with a `quality` value that is neither `normal` nor `high`
- **THEN** the submission is refused
- **AND** nothing is queued

#### Scenario: Both surfaces agree

- **WHEN** the same document is submitted with the same `quality` value over REST and through the MCP tool
- **THEN** both are read with the same render resolution and the same detector bound

### Requirement: An operator configures a mode as one pair, and a pair that reads garbage is refused at startup

Each mode's pair SHALL be one setting holding both numbers. No setting SHALL change one half of a pair on its own. The
service SHALL refuse to start with a pair whose downscale ratio, the long side of the largest page the mode supports
divided by its detector bound, exceeds 3.3, the largest ratio measured to read every line correctly.

#### Scenario: An operator retunes a mode

- **WHEN** a mode's setting is given a new pair whose ratio is within the ceiling
- **THEN** the service reads that mode's pages with both new numbers

#### Scenario: A pair beyond the measured ratio

- **WHEN** a mode's setting is given a pair whose ratio exceeds 3.3 at the largest page the mode supports
- **THEN** the service refuses to start, naming the pair and the ratio

#### Scenario: A malformed pair

- **WHEN** a mode's setting is not two positive whole numbers separated by a colon
- **THEN** the service refuses to start

### Requirement: Oversized input is shrunk to the largest size its mode supports, then read

The largest size a mode supports SHALL be the long side of a US Legal page, 14 inches, at the mode's render
resolution. A PDF page whose long side at the mode's resolution would exceed that size SHALL be rendered at the lower
scale that brings its long side to that size. An image frame whose long side exceeds that size SHALL be downscaled to
it with its aspect ratio kept. No page or frame SHALL be scaled up. An oversized page or image SHALL NOT be refused
for its size.

#### Scenario: An A4 page scanned at 300 dpi

- **WHEN** a 2480 x 3508 image is submitted in `high` mode
- **THEN** it is accepted
- **AND** it is read at its own size

#### Scenario: The same scan in normal mode

- **WHEN** a 2480 x 3508 image is submitted in `normal` mode
- **THEN** it is read downscaled to a long side of 2100 px with its aspect ratio kept

#### Scenario: A page larger than US Legal

- **WHEN** a PDF page larger than US Legal is submitted in `high` mode
- **THEN** it is rendered with its long side at 4200 px rather than at 300 dpi

#### Scenario: A small image

- **WHEN** an image smaller than the mode's largest supported size is submitted
- **THEN** it is read at its own size and not scaled up

### Requirement: Only absurd input is refused for its pixels, on its own setting

The service SHALL refuse a raster image that declares, in any of its frames, more pixels than a configured source
pixel ceiling, and SHALL refuse nothing else on pixel grounds. The ceiling SHALL be its own setting, separate from
every quality mode, and SHALL default to 89,478,485, Pillow's own decompression-bomb threshold. The check SHALL run at
submission, from the header, before any pixel buffer is allocated. The image library's process-wide
decompression-bomb limit SHALL be set from this setting and from no other. A refusal SHALL use the existing
oversized-input error code and status, and its detail SHALL name the pixel count and the ceiling.

#### Scenario: A decompression bomb

- **WHEN** a small file declaring more pixels than the ceiling is submitted
- **THEN** it is refused with `FILE_TOO_LARGE` during the header read
- **AND** no full-size pixel buffer is allocated
- **AND** nothing is queued

#### Scenario: A later frame above the ceiling

- **WHEN** a multi-frame TIFF whose first frame is within the ceiling and whose second frame is above it is submitted
- **THEN** it is refused with `FILE_TOO_LARGE`

#### Scenario: A PDF with a physically enormous page

- **WHEN** a PDF whose page would exceed the source pixel ceiling if rendered at the mode's resolution is submitted
- **THEN** it is accepted and read at the mode's largest supported size

#### Scenario: The image library's guard follows the setting

- **WHEN** the source pixel ceiling is changed and the service restarted
- **THEN** the image library's own decompression-bomb limit is the new value in both the API process and the worker

### Requirement: A page is allowed the time its own engine needs

A page SHALL be allowed a configured headroom multiple of the worst page measured on the detection model that reads
it, and the headroom SHALL be the service's only configured time input. A detection model with no measurement SHALL
be allowed the slowest measured figure. A document's reading budget and the grace before a worker that overran it is
replaced SHALL use the document's own engine's allowance. The reading ceiling and the maximum lifetime SHALL use the
slowest engine any accepted language can load. The poll hint and the queue-full retry hint SHALL count every page
ahead at its own engine's allowance.

#### Scenario: An English page in high mode

- **WHEN** an English document is read in `high` mode
- **THEN** each page is allowed 4.5 x 25.1 s at the default headroom
- **AND** a dense page taking the measured 25.1 s does not fail the document

#### Scenario: An English page is not charged a slower engine's allowance

- **WHEN** an English document is read while an operator has opted a language back in on `PP-OCRv5_server_det`
- **THEN** its budget is its pages x 4.5 x 25.1 s at the default headroom
- **AND** a page in the opted-in language is allowed 4.5 x 96.0 s

#### Scenario: The ceilings follow the slowest reachable engine

- **WHEN** every supported language reads with the `PP-OCRv6_small` pair
- **THEN** the reading ceiling and the maximum lifetime are computed from the small pair's allowance

#### Scenario: The headroom moves every duration

- **WHEN** the headroom is changed and the service is restarted
- **THEN** every allowance, budget, grace, ceiling, lifetime and hint changes with it

### Requirement: The detector bound is applied per request without a second engine

The service SHALL apply the request's mode's detector bound on each call to the OCR engine, as a longest-side bound.
Both modes SHALL share the engine a language resolves to, and the engine cache key SHALL NOT include the mode or the
bound.

#### Scenario: Two modes, one language

- **WHEN** one document is read in `normal` mode and another in `high` mode in the same language
- **THEN** both are read by one cached engine
- **AND** each call bounds detection to its own mode's value

### Requirement: Every preprocessing step is named, never inherited from the library

The service SHALL build every OCR engine with page orientation, unwarping and text line orientation named explicitly,
and SHALL pass all three on every call to the engine, so no preprocessing step is decided by a library default. For
every request page orientation SHALL run, text line orientation SHALL run with one text line per classifier call, and
unwarping SHALL NOT run unless the request asks for it. Every engine SHALL be built identically, and the engine cache
key SHALL remain the model pair. The container image SHALL carry every model an accepted language can load, the
preprocessing models included, so that no model is downloaded while a request is read.

#### Scenario: A clean page is read without unwarping

- **WHEN** a clean flat scan is submitted without `straighten`
- **THEN** the page is corrected for page orientation and text line orientation
- **AND** it is not unwarped

#### Scenario: A page turned upside down

- **WHEN** a scan turned 180 degrees is submitted
- **THEN** it is turned upright before its lines are detected

#### Scenario: A page mixing upright and upside-down lines

- **WHEN** a page carries upright lines and upside-down lines in any order
- **THEN** each line's orientation is decided on that line alone

#### Scenario: The shipped image carries only what a supported language loads

- **WHEN** the image is built with the shipped `SUPPORTED_LANGUAGES`
- **THEN** it carries the `PP-OCRv6_small` pair and the three preprocessing models
- **AND** it carries no `PP-OCRv5_server_det`, `korean_PP-OCRv5_mobile_rec` or `eslav_PP-OCRv5_mobile_rec`

### Requirement: A caller may ask for a page to be straightened

Job submission SHALL accept an optional boolean `straighten` parameter on both surfaces, a form field on REST and an
argument on the MCP tool. When `straighten` is omitted it SHALL be `false`. When it is `true` unwarping SHALL run on
every page of that document in addition to the steps every request gets. A value that is not a boolean SHALL be
refused before any work is queued. The choice SHALL be recorded with the job and reported with its result beside the
quality mode. A straightened request SHALL be read by the same cached engine as a plain request in the same language.
The documentation of both surfaces SHALL say that `straighten` is meant for phone photos of bent, curled or crumpled
paper, is recommended with `quality=high`, and is harmful on clean scans and PDFs.

#### Scenario: A crumpled photo

- **WHEN** a phone photo of crumpled paper is submitted with `straighten=true`
- **THEN** every page is unwarped before its lines are detected
- **AND** the result reports `straighten` as `true`

#### Scenario: Omitted straighten

- **WHEN** a document is submitted without `straighten` on either surface
- **THEN** no page is unwarped
- **AND** the result reports `straighten` as `false`

#### Scenario: Not a boolean

- **WHEN** a document is submitted with a `straighten` value that is not a boolean
- **THEN** the submission is refused
- **AND** nothing is queued

#### Scenario: One engine for both

- **WHEN** one document is read with `straighten=true` and another without it, in the same language
- **THEN** both are read by one cached engine
- **AND** only the first is unwarped

#### Scenario: A record from before straightening existed

- **WHEN** a job record written without a `straighten` field is read
- **THEN** it reads as `straighten=false`

### Requirement: A language the service does not read is refused at submission

The service SHALL refuse a submission whose language is outside `SUPPORTED_LANGUAGES` on both surfaces before anything
is fetched, stored or queued, and SHALL issue no job identifier for it. The refusal SHALL carry the code
`UNSUPPORTED_LANGUAGE`, SHALL answer HTTP 400 on the REST surface, and SHALL name every supported language without
echoing the language the caller sent. `ru` and `korean` SHALL NOT be supported languages by default.

#### Scenario: A Korean submission over REST

- **WHEN** `POST /v1/ocr/jobs` carries `lang=korean` at the shipped defaults
- **THEN** the answer is HTTP 400 with `{"code": "UNSUPPORTED_LANGUAGE", "detail": "Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan"}`
- **AND** it carries no `job_id` and no `Location` header
- **AND** nothing is queued

#### Scenario: A Russian submission over MCP

- **WHEN** `ocr_submit` is called with `lang=ru` at the shipped defaults
- **THEN** the tool fails with `UNSUPPORTED_LANGUAGE: Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan`
- **AND** the URI is never fetched
- **AND** nothing is queued

#### Scenario: An operator's own allowlist

- **WHEN** `SUPPORTED_LANGUAGES` is configured to another list
- **THEN** a language on it is accepted
- **AND** the refusal of any other language names that list
