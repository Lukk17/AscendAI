# ADR-007: Name the OCR models explicitly, ship PP-OCRv6 small, and key the engine cache by the pair

## Status

Accepted — 2026-09-24

## Context

Until this decision the service called `PaddleOCR(lang=...)` and let the library choose the models. Under
`paddleocr==3.6.0` that choice, made by `PaddleOCR._get_ocr_model_names` in `paddleocr/_pipelines/ocr.py`, gave every
one of the twelve codes in `SUPPORTED_LANGUAGES` the same detector, `PP-OCRv5_server_det`, and a recognition model
per language:

| Language code | Detection | Recognition |
|---|---|---|
| `en` | `PP-OCRv5_server_det` | `en_PP-OCRv5_mobile_rec` |
| `pl`, `de`, `fr`, `es`, `it`, `pt`, `nl` | `PP-OCRv5_server_det` | `latin_PP-OCRv5_mobile_rec` |
| `ch`, `japan` | `PP-OCRv5_server_det` | `PP-OCRv5_server_rec` |
| `ru` | `PP-OCRv5_server_det` | `eslav_PP-OCRv5_mobile_rec` |
| `korean` | `PP-OCRv5_server_det` | `korean_PP-OCRv5_mobile_rec` |

That detector is 88.4 MB of artifacts (84.3 MiB) and, per [ADR-006](ADR-006-detector-input-bound.md), 94 percent of
one call's transient memory and most of its time. No document in this repository named it. It was a default, and the
service inherited both its cost and the absence of any record that it had been chosen.

`paddleocr==3.7.0` ships PP-OCRv6 in three sizes. On PaddleOCR's own published head-to-head, the same test set per
row, timings on an Intel Xeon (vendor numbers, not measured here):

| Family member | Detection | Recognition | Seconds per image |
|---|---|---|---|
| `PP-OCRv5_server` | 81.6 | 78.1 | 2.04 |
| `PP-OCRv6_small` | 84.1 | 81.3 | 0.79 |
| `PP-OCRv6_medium` | 86.2 | 83.2 | 2.05 |

The new family is also one recognition model for 50 languages, with roughly 200 diacritical characters added, where
the old family needed a different recognition model per script. Its coverage set in 3.7.0 is
`{ch, chinese_cht, en, japan}` plus every Latin language except `pi`, which takes in ten of this service's twelve
codes and leaves out `ru` and `korean`.

Two details about 3.7.0 shape the decision. Its own default for a covered language is the **medium** member, so
upgrading the pin and changing nothing else would swap one unchosen model for another. And passing model names
alongside `lang` makes the library warn and ignore the language, so naming the models means not passing a language
at all.

## Decision

**Name the models.** `OcrService._get_engine` constructs `PaddleOCR` with `text_detection_model_name` and
`text_recognition_model_name`, and never with `lang`. The allowlist check against `SUPPORTED_LANGUAGES` stays in
front of everything, so a caller-controlled language string still cannot reach a model name.

**Ship the small member, from configuration.** `OCR_TEXT_DETECTION_MODEL` defaults to `PP-OCRv6_small_det` and
`OCR_TEXT_RECOGNITION_MODEL` to `PP-OCRv6_small_rec`. Small rather than medium because it beats the outgoing models
on both published accuracy axes while running 2.6 times faster, where medium buys 2 further points of detection at
the outgoing models' speed. This service's own measured per-page cost is 51 to 94 seconds on its 4.0 CPU allocation,
and a per-page deadline is the failure mode the previous change was written to fix, so speed here is not a luxury.
Both values are settings, so moving to medium is two environment variables and a rebuild.

**Name the exceptions too.** `LANGUAGE_MODEL_OVERRIDES` in `src/config/config.py` maps each language outside the
family's coverage to its own pair. Today that is `ru` to `PP-OCRv5_server_det` / `eslav_PP-OCRv5_mobile_rec` and
`korean` to `PP-OCRv5_server_det` / `korean_PP-OCRv5_mobile_rec`, which is exactly what those two ran before. It is a
code constant rather than a setting, because it is a property of the library's model catalogue and not of a
deployment.

**Key the engine cache by the resolved pair.** `OcrService._engines` is an `OrderedDict[ModelPair, PaddleOCR]`. Ten
languages now resolve to one pair, so keying by language would hold ten identical engines. Keying by the pair means
the second language to arrive costs nothing. `ENGINE_CACHE_MAX_SIZE` therefore counts engines rather than languages.
It stays at 2, and its reason changes completely: it is the pre-cached default pair plus one slot, so a single `ru`
or `korean` request cannot evict the pair almost every request uses.

**Bake what the settings name.** The Dockerfile's warm-up `RUN` constructs one engine from the two settings instead
of naming two languages, so the image cannot bake a pair the service does not load. Detection and recognition
artifacts in the image drop from 104.6 MB to 31.6 MB.

## Rejected alternatives

**Bump the pin and change nothing else.** Rejected: 3.7.0 then selects `PP-OCRv6_medium`, which is an unchosen model
at the old speed, and the service is back to inheriting a default it never recorded.

**Pass `ocr_version="PP-OCRv6"` with `lang`.** Fewer moving parts, and rejected for two reasons: it resolves to the
medium member, and the actual model names stay in a table this repository does not own, which is the problem rather
than the fix.

**Point `ru` and `korean` at the default pair too.** Rejected outright: the v6 recognition model carries no Cyrillic
or Hangul dictionary, so this would not read those languages worse, it would stop reading them.

**Keep `lang=` for `ru` and `korean` only.** Rejected: it reintroduces implicit selection on the two languages least
likely to be checked.

**Raise `ENGINE_CACHE_MAX_SIZE` to 3, so every possible engine stays resident.** Rejected: it adds a resident engine
to a memory ceiling nobody can re-measure on the current host, to serve a workload that alternates Russian and
Korean.

**Lower it to 1, matching what the image bakes.** Rejected: one off-family request would evict the pair everything
else uses, and the next request would pay a full warm-up.

## Consequences

- The models in use are readable from `config.py` and from one environment table, and a change of family member is a
  configuration change rather than a code change.
- Ten of the twelve supported languages share one warm engine. `ru` and `korean` each bring their own, and neither is
  baked into the image, so a first request in either downloads its pair (96.5 MB and 102.3 MB).
- `ascendocr_engine_cache_evictions_total` is labelled `engine` rather than `language`, carrying
  `"<detection>/<recognition>"`. Nothing outside the service read the old label.
- The memory model in [ADR-006](ADR-006-detector-input-bound.md) and in
  [07-deployment-view.md](../arc42/07-deployment-view.md) was fitted against `PP-OCRv5_server_det`. It stays exact
  for `ru` and `korean` and becomes an upper bound for everything else. No figure was lowered on the strength of an
  expectation. Re-measuring is task 4.6 of `openspec/changes/upgrade-ocr-to-ppocrv6/tasks.md`.
- The accuracy claim behind the family choice is the vendor's benchmark, not a measurement against the owner's own
  documents. The end-to-end specs that would catch a regression first are 2 (English canaries) and 3 (Polish
  diacritics), and both are listed as verification tasks in the same change.
- Rolling back to the old models for the common path is two environment variables and a restart. Rolling back to the
  old per-language mapping, where `en` and the Latin languages get different recognition models, means reverting the
  change.

## Amendment, 2026-09-25: `ru` and `korean` switched off

The two exceptions this record names are gone from the service. `PP-OCRv5_server_det`, the detector both loaded,
was measured as a Linux container's cgroup peak at 9297 MiB on an A4 page and 12754 MiB on a 4200 x 4200 px page in
`high` mode, and 5958 MiB in `normal` mode, the worst of them above the 12 GiB limit the container then carried.
`SUPPORTED_LANGUAGES` no longer lists either, `LANGUAGE_MODEL_OVERRIDES` is empty, and the image bakes only the
default pair, so a request in either is refused at submission with `UNSUPPORTED_LANGUAGE` (ADR-002). The mechanism stays, because bringing
them back is expected to use it: pairing `PP-OCRv6_small_det` with the `korean_` and `eslav_` PP-OCRv5 mobile
recognisers, measured with and without straightening, and restored only if accuracy holds. That is an open task in
`openspec/changes/fix-ocr-page-resolution/tasks.md`. The consequence above that `ru` and `korean` each bring their
own engine no longer applies, and `ENGINE_CACHE_MAX_SIZE` stays at 2 with its second slot empty. See
[ADR-011](ADR-011-explicit-preprocessing-and-straighten.md).

## Related

- `openspec/changes/upgrade-ocr-to-ppocrv6/` — the proposal, the design decisions, and the verification tasks.
- [ADR-006](ADR-006-detector-input-bound.md) — the detector input bound, amended for the detector swap.
- [ADR-005](ADR-005-fixed-pdf-render-resolution.md) — the fixed 144 dpi rendering these models read pages at.
- `apps/ascend-ocr/src/config/config.py` — `OCR_TEXT_DETECTION_MODEL`, `OCR_TEXT_RECOGNITION_MODEL`, `ModelPair`,
  `LANGUAGE_MODEL_OVERRIDES`.
- `apps/ascend-ocr/src/service/ocr_service.py` — `_resolve_model_pair`, `OcrService._get_engine`.
