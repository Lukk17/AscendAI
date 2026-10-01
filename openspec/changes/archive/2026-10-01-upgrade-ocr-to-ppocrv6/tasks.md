Every command below runs from `apps/ascend-ocr/` through that module's own virtual environment, and always as
`python.exe -m <tool>`: the console-script shims in that environment are broken and exit 1 silently, so
`.venv/Scripts/ruff.exe` and friends prove nothing. On Windows the interpreter is `.venv/Scripts/python.exe`, on
Linux and macOS `.venv/bin/python`. The gate is `--cov-fail-under=100` with `--cov-branch`, already in
`pyproject.toml`'s `addopts`, so a bare `python.exe -m pytest` runs it.

Sections 1 to 3 and 5 were done on a host at 97 percent memory use with 0.7 GiB free. Section 4 is everything that
host could not run: no inference, no memory measurement, and an unreliable test suite. Nothing in section 4 is
ticked, and nothing in it should be ticked by anyone who has not run the command beside it and read the output.

## 1. Confirm the dependency facts before changing the pin

- [x] 1.1 Confirm `paddleocr==3.7.0` does not drag `paddlepaddle`. Verified from metadata, three ways.
      `paddleocr` 3.7.0's PyPI `requires_dist` is `paddlex[ocr-core]<3.8.0,>=3.7.0`, `PyYAML>=6`, `requests`,
      `aiohttp>=3.8.0`, `typing-extensions>=4.12`, the same five entries as 3.6.0 with only the paddlex range moved.
      `paddlex` 3.7.2's own `requires_dist` names eighteen core packages and six `ocr-core` extras
      (`imagesize`, `opencv-contrib-python==4.10.0.84`, `pyclipper`, `pypdfium2>=4`, `python-bidi`, `shapely`) and is
      identical package-for-package to the installed 3.6.1, with `paddlepaddle` in neither. And paddlex's runtime
      check for it is presence-only, `importlib.util.find_spec("paddle")` in `paddlex/utils/deps.py`, with the
      relevant block byte-identical between 3.6.1 and 3.7.2, so no version specifier exists to conflict with
      `paddlepaddle==3.3.1`. Conclusion: the pin holds and paddlex is the only package that moves.
- [x] 1.2 Confirm the new model names exist rather than assuming them from a release note.
      `PP-OCRv6_small_det` and `PP-OCRv6_small_rec` appear in `paddlex/configs/modules/text_detection/` and
      `paddlex/configs/modules/text_recognition/`, in `paddlex/modules/text_detection/model_list.py` and
      `paddlex/modules/text_recognition/model_list.py`, and in `ALL_MODELS` in
      `paddlex/inference/utils/official_models.py`, all read from the downloaded 3.7.2 wheel. `medium` and `tiny`
      exist alongside them.
- [x] 1.3 Record which of this service's twelve declared languages the new family covers. Read from
      `_PPOCRV6_LANGS` and `LATIN_LANGS` in the 3.7.0 wheel: ten are covered (`en`, `pl`, `de`, `fr`, `es`, `it`,
      `pt`, `nl`, `ch`, `japan`), two are not (`ru`, `korean`). Both tables are in design.md's Context section.
- [x] 1.4 Record the artifact sizes, so "smaller" is a number rather than an adjective. Hugging Face repository
      trees, summed per repository, in design.md's Context section. Today's detector is 88.4 MB (84.3 MiB), the new
      default pair is 31.6 MB for both models together.

## 2. Code

- [x] 2.1 Bump `paddleocr==3.6.0` to `paddleocr==3.7.0` in `pyproject.toml`, leaving `paddlepaddle==3.3.1` alone.
- [x] 2.2 Add `OCR_TEXT_DETECTION_MODEL` and `OCR_TEXT_RECOGNITION_MODEL` to `Settings`, defaulting to
      `PP-OCRv6_small_det` and `PP-OCRv6_small_rec`, each constrained by a pattern so a caller-supplied environment
      value cannot be arbitrary text.
- [x] 2.3 Add the `ModelPair` frozen dataclass and the `LANGUAGE_MODEL_OVERRIDES` table for the two languages the
      default family does not cover, and assert in a test that every key of that table is a supported language.
- [x] 2.4 Rewrite `ENGINE_CACHE_MAX_SIZE`'s comment so it says what the number now counts. Value stays 2
      (design.md Decision 4).
- [x] 2.5 Add `_resolve_model_pair(language)` to `ocr_service.py` and have `_get_engine` construct `PaddleOCR` with
      `text_detection_model_name` and `text_recognition_model_name` instead of `lang`.
- [x] 2.6 Key `OcrService._engines` by `ModelPair`, including the `move_to_end` promotion and the eviction path.
- [x] 2.7 Rename the eviction counter's label from `language` to `engine` and log the evicted pair.
- [x] 2.8 Point the Dockerfile's warm-up `RUN` at the two settings so the baked pair cannot drift from the default.

## 3. Tests

Each of these was seen to fail before it passed. The pre-change behaviour was restored in
`src/service/ocr_service.py` (cache keyed by language, `lang=` on the constructor), the class was run against it, and
eight of the cases below failed: 3.1 through 3.7. The file was restored from a checksum-verified copy afterwards and
the full gate re-run.

- [x] 3.1 Two languages that resolve to the same pair share one engine, and the constructor is called once.
- [x] 3.2 Two languages that resolve to different pairs get one engine each.
- [x] 3.3 `_get_engine` passes both model names and no `lang`, for an in-family language and for an override
      language.
- [x] 3.4 An operator-supplied pair reaches the constructor, so the settings are genuinely the source.
- [x] 3.5 The override table wins over the configured default for its own languages, and only for those.
- [x] 3.6 LRU eviction still evicts the least recently used engine, now keyed by pair, and the counter is labelled
      with the evicted pair.
- [x] 3.7 The detector bound is still not part of the cache key.
- [x] 3.8 The unsupported-language refusal still happens before any model name is resolved.
- [x] 3.9 Every key of `LANGUAGE_MODEL_OVERRIDES` is in `SUPPORTED_LANGUAGES`, and the shipped defaults are the
      small pair.

## 4. Verification this host could not run

Everything here needs a machine with memory to spare. Run them in order: 4.1 gates the rest.

- [x] 4.1 Install the new pin and run the full gate. Four commands, from `apps/ascend-ocr/`:

      .venv/Scripts/python.exe -m pip install -e ".[dev]"
      .venv/Scripts/python.exe -m ruff check .
      .venv/Scripts/python.exe -m mypy src
      .venv/Scripts/python.exe -m pytest

      Verify: `pip` reports `paddleocr-3.7.0` and a `paddlex` 3.7.x, and reports nothing about `paddlepaddle`,
      `python.exe -m pip show paddlepaddle` still says 3.3.1, ruff and mypy are clean, and pytest passes with
      coverage at 100 percent. A `pytest` failure that names `MemoryError`, a killed worker, or a `paddle` import that
      could not allocate is a host symptom, not a defect: free memory and run it again rather than changing code.
      Done 2026-09-24: `pip show` in the module venv reports paddleocr 3.7.0, paddlex 3.7.2 and paddlepaddle 3.3.1. ruff check and format clean, mypy clean, pytest 719 passed and 7 skipped at 100 percent line and branch coverage.
- [x] 4.2 Rebuild the image so it bakes the new pair. Owner's command, not the agent's. Verify the build log shows
      the warm-up `RUN` fetching `PP-OCRv6_small_det` and `PP-OCRv6_small_rec` and no `PP-OCRv5_server_det`, and
      that `docker exec ascend-ocr ls ~/.paddlex/official_models` lists the new pair.
      Done 2026-10-01: the image is rebuilt from this tree, the startup banner of image `8fe58a06032a` reported the 113.0 s page allowance that only `PP-OCRv6_small_det` gives, and specs 1 to 20 passed against images built that day, the last `33104618230738`.
- [x] 4.3 Prove the response shape survived the model swap, which `_extract_text_lines` depends on. Run end-to-end
      spec 2 (`apps/ascend-ocr/e2e/testing/2-ocr-english-test.md`) after asking the owner which scenario from
      `docs/E2E_RUN_SCENARIOS.md` to run under. It is engine-bound, so it runs alone with no other runner active.
      Verify: HTTP 200, the canary substrings present, and `lines` non-empty, which is what proves `rec_texts`,
      `rec_scores` and `dt_polys` are still the keys the library returns.
      Done 2026-10-01: spec 2 passed against image `33104618230738` on the job interface, which replaced the synchronous 200 answer this task names.
- [x] 4.4 Prove Polish diacritics survived, the one caller-visible risk. End-to-end spec 3
      (`3-ocr-polish-test.md`), same concurrency rule, same scenario question. Verify the recognised text still
      carries a character from `{ś, ż, ą, ę, ć, ó, ł, ń, ź}` and the canary substrings. If it does not, the pair is
      revertible from the environment without a rebuild (design.md, Migration Plan).
      Done 2026-10-01: spec 3 passed with the Polish diacritics and the canary substrings present.
- [x] 4.5 Run specs 4 and 6 (`4-ocr-default-language-test.md`, `6-mcp-ocr-test.md`), one at a time, to cover the
      default-language path and the MCP surface against the new models.
      Done 2026-10-01: specs 4 and 6 passed, spec 6 against image `33104618230738`.
- [x] 4.6 Measure what the new pair actually costs, and only then update the numbers this change deliberately left
      conservative. Read `memory.peak` from the container's cgroup after one A4 page, and time one page the way
      task 1.2 of `stop-ocr-getting-stuck-on-large-jobs` timed it. Verify by updating, in the same pass:
      `_PER_CACHED_LANGUAGE_MIB` and the per-megapixel constants in `src/config/startup_banner.py` if they moved,
      the memory model in `docs/architecture/arc42/07-deployment-view.md`, and the ascend-ocr paragraphs in
      `docs/architecture/memory-budget.md`. Until this task reports, every one of those is an upper bound fitted
      against the old detector and is correct as such.
      Reconciled on 2026-09-24 with `read-long-documents` task 12.1, still open: the one-page peak and the per-page
      time this task measures are the figures `read-long-documents` design.md already records from the owner's
      measurement, about 440 MB flat and 4.1 s to 10.0 s for one A4 page at 300 dots per inch (Superseded 2026-09-25: measured as a Linux container's cgroup `memory.peak`, one A4 page at 300 dpi peaks at 1016 MiB, see `fix-ocr-page-resolution` design.md Decision 10.) That table is their
      one account. This task records its container reading against it there, confirming or moving it, and carries
      the result into the three places above rather than writing a second account. `read-long-documents` task 1.2
      owns the separate per-page retained-result term and the hundred page timing.
      Done: measured as a Linux container's cgroup `memory.peak` on the `PP-OCRv6_small` pair (images `7b2cb25e7360` and `9c100951f59b`) and carried into the startup banner, the deployment view and `memory-budget.md` by `fix-ocr-page-resolution` tasks 6.6, 9.15 and 9.16, which own that one account.
- [ ] 4.7 Decide with the owner whether the published accuracy gain holds on his own documents, using the same
      five real documents ADR-006 was measured against, and whether the medium member is worth 2.6 times the time
      (design.md, Open Question 1).
- [x] 4.8 Decide with the owner whether this ships as a version bump, and write the `CHANGELOG.md` entry that goes
      with it. Left undone deliberately: the changelog's topmost version is what the release workflow publishes, so
      bumping it is a release decision rather than a documentation one.
      Done 2026-10-01: ascend-ocr ships as 0.3.0 with its `CHANGELOG.md` entry, commit `8173593`.

## 5. Documentation

- [x] 5.1 `apps/ascend-ocr/AGENTS.md`: the tech-stack pin, the two new environment variables, and the
      `ENGINE_CACHE_MAX_SIZE` entry that currently explains itself by naming two pre-cached languages.
- [x] 5.2 `apps/ascend-ocr/README.md`: the tech-stack line, the architecture diagram's "per language" engine node,
      and the settings count in the configuration section.
- [x] 5.3 `apps/ascend-ocr/docs/CONFIGURATION.md`: the two new variables in the OCR engine table, and the
      `ENGINE_CACHE_MAX_SIZE` row.
- [x] 5.4 arc42 04 (the engine cache section), 07 (the environment table, the memory model, and the Docker build
      section), 08 (the crosscutting cache description), 11 (the pre-cached-languages risk row) and 12 (the glossary
      entries naming the cache's key type and the pin). Four more chapters carried a claim the change falsified and
      were corrected in the same pass: 02 (the pinned version and the Dockerfile warm-up it quotes), 05 (the
      `OcrService` building-block row), 06 (the `_get_engine` step in the request sequence) and 09 (the ADR index,
      which was also missing ADR-005 and ADR-006 before this change added ADR-007).
- [x] 5.5 Amend [ADR-006](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md) where it says the
      cache key is the language and where it describes the detector by its export geometry. Amendment, not a
      rewrite: its measurements were taken against the old detector and stay true of it.
- [x] 5.6 Add ADR-007 recording the family, the member, the two languages that keep the old pair, and the cache
      key, and add it to the decisions index.
- [x] 5.7 `docs/architecture/memory-budget.md` at the monorepo level states the per-cached-language cost and the
      two languages the image bakes, both of which this change moves. A dated paragraph beside the ascend-ocr
      formula records what changed, states that every figure there is now exact for `ru` and `korean` and an upper
      bound elsewhere, and points at task 4.6. No measured number in that document was altered.
