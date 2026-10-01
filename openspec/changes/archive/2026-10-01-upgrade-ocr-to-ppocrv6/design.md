## Context

Everything below rests on four sources, and each claim says which one it came from.

1. **The installed tree.** `apps/ascend-ocr/.venv`, read directly: `paddleocr` 3.6.0, `paddlex` 3.6.1,
   `paddlepaddle` 3.3.1, and the body of `PaddleOCR._get_ocr_model_names` in
   `paddleocr/_pipelines/ocr.py`.
2. **The 3.7.0 and 3.7.2 wheels**, downloaded with `pip download --no-deps --only-binary :all:` into a scratch
   directory and read as zip archives. Nothing was installed, so the running environment is still 3.6.0 and the
   suite in this repository still runs against it until the pin is applied and the environment updated.
3. **PyPI metadata** for `paddleocr` 3.6.0 and 3.7.0 and for `paddlex` 3.6.1 and 3.7.2.
4. **Hugging Face repository trees** for each model named here, which is where the artifact sizes come from.

What is not a source: any measurement of memory, speed, or accuracy taken on this host. The host was at 97 percent
memory use with 0.7 GiB free while this was written, which rules out running an inference at all. Every vendor
number in this document is labelled as a vendor number, and every gap that needs a local measurement is a task in
[tasks.md](tasks.md) with the command that closes it.

### What the software does today

`OcrService._get_engine` calls `PaddleOCR(lang=language, enable_mkldnn=False, ...)`. The library then resolves the
language to a model pair on its own. Under 3.6.0 the twelve codes in `SUPPORTED_LANGUAGES` resolve like this:

| Language code | Detection model | Recognition model |
|---|---|---|
| `en` | `PP-OCRv5_server_det` | `en_PP-OCRv5_mobile_rec` |
| `pl`, `de`, `fr`, `es`, `it`, `pt`, `nl` | `PP-OCRv5_server_det` | `latin_PP-OCRv5_mobile_rec` |
| `ch`, `japan` | `PP-OCRv5_server_det` | `PP-OCRv5_server_rec` |
| `ru` | `PP-OCRv5_server_det` | `eslav_PP-OCRv5_mobile_rec` |
| `korean` | `PP-OCRv5_server_det` | `korean_PP-OCRv5_mobile_rec` |

One detector for everything, five distinct pairs, and a cache keyed by language that builds up to twelve engines for
those five pairs. Seven Latin languages share one pair and get seven cache entries.

### What 3.7.0 resolves instead

`_get_ocr_model_names` in the 3.7.0 wheel introduces `PP-OCRv6` and a coverage set:

```python
_PPOCRV6_UNSUPPORTED_LATIN_LANGS = frozenset({"pi"})
_PPOCRV6_LANGS = frozenset({"ch", "chinese_cht", "en", "japan"}) | (LATIN_LANGS - _PPOCRV6_UNSUPPORTED_LATIN_LANGS)
```

`LATIN_LANGS` in `paddleocr/_utils/langs.py` contains `de`, `es`, `fr`, `it`, `nl`, `pl`, `pt`, so ten of this
service's twelve codes land inside the set. For any of them, with `ocr_version` left unset, 3.7.0 returns
`PP-OCRv6_medium_det` / `PP-OCRv6_medium_rec`. `ru` falls to the `ESLAV_LANGS` branch and `korean` to its own, and
both keep the PP-OCRv5 pair from the table above.

### The artifact sizes, measured

Hugging Face repository trees under `PaddlePaddle/<model>`, summed over every file in the repository (so including
the README and `inference.json`, not only the weights):

| Model | Repository total |
|---|---|
| `PP-OCRv5_server_det` (today's detector) | 88.4 MB, which is 84.3 MiB |
| `PP-OCRv5_server_rec` | 85.2 MB |
| `en_PP-OCRv5_mobile_rec` | 8.0 MB |
| `latin_PP-OCRv5_mobile_rec` | 8.2 MB |
| `eslav_PP-OCRv5_mobile_rec` | 8.1 MB |
| `korean_PP-OCRv5_mobile_rec` | 13.9 MB |
| `PP-OCRv6_small_det` | 10.1 MB |
| `PP-OCRv6_small_rec` | 21.5 MB |
| `PP-OCRv6_medium_det` | 62.3 MB |
| `PP-OCRv6_medium_rec` | 76.9 MB |

The 84.3 MiB in the brief that opened this change and the 88.4 MB read here are the same number in different units,
which is the cross-check that the detector named in the brief and the detector in the resolution table are the same
artifact.

## Goals / Non-Goals

Goals:

- Run a model family the service chose, on a version that ships it, with the choice written down where an operator
  can read and change it.
- Stop paying for a second engine when two languages resolve to one model pair.
- Ship an image whose baked models are the ones the service will load.
- Leave every number that cannot be re-measured today exactly as it is, and write down how to measure it.

Non-Goals:

- Changing `text_det_limit_type`, `text_det_limit_side_len`, `OCR_DETECTOR_MAX_SIDE`, or
  `OCR_MAX_INFERENCE_PIXELS`. The detector-input decision is [ADR-006](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md)
  and its numbers are the owner's, measured against his own documents. Nothing here reopens them.
- Touching `enable_mkldnn`. It is a separate experiment.
- Reducing any memory figure. The new detector is expected to cost less, and expected is not measured.
- Widening `SUPPORTED_LANGUAGES` to the 50 languages the new family claims. The allowlist is a memory and
  correctness guard, and widening it is a decision with its own evidence to gather.

## Decisions

### Decision 1: PP-OCRv6, and the small member rather than the medium one

The family is decided by the vendor table in [proposal.md](proposal.md): the small member beats the incumbent on
detection (84.1 against 81.6) and on recognition (81.3 against 78.1) while running 2.6 times faster (0.79 s against
2.04 s per image on an Intel Xeon). There is no axis on which the incumbent wins, so the only real question is small
against medium.

Medium is 2 points of detection and 1.9 points of recognition better than small, at 2.05 s against 0.79 s. That is
the incumbent's speed for the incumbent's cost, and this service's own measured per-page time on its 4.0 CPU
allocation is 51 to 94 seconds (task 1.2 of `stop-ocr-getting-stuck-on-large-jobs`), which is what a per-page
allowance of 150 seconds in `compose.yaml` exists to cover. A member that is 2.6 times faster is the difference
between a document that finishes inside its budget and one that does not, and the budget is the failure this
service's previous change was written to fix.

Reconciled on 2026-09-24. The 51 to 94 seconds and the 150 second allowance above describe the pair this change
replaced. On the pair it installs, one A4 page was measured at 4.1 s to 10.0 s, and that measurement is recorded in
[read-long-documents](../read-long-documents/design.md). The per-page allowance itself is owned by
[fix-ocr-page-resolution](../fix-ocr-page-resolution/design.md) (its Decision 8), which replaced the single 45 s
read-long-documents first settled with one allowance per engine.

Small it is, as the shipped default. Medium stays one environment variable pair away, and the artifact sizes above
say what switching costs on disk (62.3 + 76.9 MB against 10.1 + 21.5 MB).

Tiny exists too. It is not offered as a documented option because no accuracy number for it appears in the vendor
table this decision rests on, and offering a member with no published accuracy would be offering a guess. The
settings accept any model name the library knows, so nothing stops an operator from trying it.

### Decision 2: name the models, do not name the language

`PaddleOCR.__init__` in 3.7.0 branches on whether any of `text_detection_model_name`, `text_detection_model_dir`,
`text_recognition_model_name`, `text_recognition_model_dir` is set. If all four are `None` it resolves from `lang`
and `ocr_version`. If any is set it uses what it was given, and warns if `lang` was also passed:

```python
warnings.warn(
    "`lang` and `ocr_version` will be ignored when model names or model directories are not `None`.",
    stacklevel=2,
)
```

So passing both is not an option worth having: it would emit a warning on every engine construction and the `lang`
would do nothing. `_get_engine` passes the two model names and stops passing `lang`.

This does not weaken the language handling. The recognition model carries its own character dictionary, which is why
the old pairs are named per language at all, so naming `korean_PP-OCRv5_mobile_rec` says everything `lang="korean"`
used to say. The `SUPPORTED_LANGUAGES` allowlist check stays exactly where it is, in front of everything, so a
caller-controlled language string still cannot reach a model name.

An alternative was considered and rejected: pass `ocr_version="PP-OCRv6"` alongside `lang`, which is fewer moving
parts and gets the family without naming members. Rejected because it picks the medium member, which Decision 1
rejects, and because it leaves the actual model names resolved by a table this service does not own. The whole point
of the change is that the selection is visible in this repository.

### Decision 3: the two languages outside the family keep their pair, written down

`ru` and `korean` are outside `_PPOCRV6_LANGS`. Three options:

1. Point them at the default pair anyway. Rejected, and not close: the v6 recognition model has no Cyrillic or
   Hangul dictionary, so this reads Russian and Korean as garbage rather than reading them worse.
2. Let the library resolve those two implicitly, by keeping `lang=` for them. Rejected: it reintroduces exactly the
   implicit selection this change removes, on the two languages least likely to be checked.
3. Name their pair in a table beside the default. Chosen.

The table records what those two languages run today and will keep running:

```python
LANGUAGE_MODEL_OVERRIDES = {
    "ru": ModelPair("PP-OCRv5_server_det", "eslav_PP-OCRv5_mobile_rec"),
    "korean": ModelPair("PP-OCRv5_server_det", "korean_PP-OCRv5_mobile_rec"),
}
```

Two consequences worth stating rather than discovering. Those two languages keep the heavy `PP-OCRv5_server_det`
detector, so the fitted memory model stays exactly right for them and the container's ceiling is still sized for the
worst case they represent. And they are not baked into the image (Decision 5), so a first `ru` or `korean` request in
a fresh container downloads its own pair before it answers, 96.5 MB for `ru` and 102.3 MB for `korean`, which is the
behaviour every non-pre-cached language already has today and is recorded as a known risk in arc42 chapter 11.

The table is a code constant rather than a setting. It is a property of the library's model catalogue, not of a
deployment, and a deployment that wants a different pair for `ru` has the same freedom everyone has: name it.
Building an environment-variable syntax for a two-row table would be configurability nobody asked for.

### Decision 4: key the cache by the model pair, and keep `ENGINE_CACHE_MAX_SIZE` at 2 with a different reason

The cache is `OrderedDict[str, PaddleOCR]` keyed by language. Under the new resolution, `en` and `pl` and eight
others produce byte-identical engines, so the key has to become what actually distinguishes an engine: the pair of
model names. `OrderedDict[ModelPair, PaddleOCR]`, with `ModelPair` a frozen dataclass so it is hashable and reads as
a pair rather than as an anonymous tuple.

The cap then counts engines, not languages, and the twelve declared languages can produce at most three of them.
Three candidate values:

| Cap | What stays resident | What it costs | Verdict |
|---|---|---|---|
| 1 | The default pair alone | A single `ru` request evicts the pair nine tenths of traffic uses, and the next `en` request pays a full warm-up | Rejected: one off-family request poisons the cache |
| **2** | The default pair plus one off-family engine | Unchanged against today: the banner's estimate is `143 x (cap - 1)` either way | **Chosen** |
| 3 | Every engine the allowlist can produce | One more resident engine than the memory ceiling was sized for, on a host that cannot re-measure it today | Rejected: raises a ceiling nobody can check |

2 also happens to be the value in `compose.yaml` and in every document, so choosing it changes no deployed number
while its meaning changes completely. That is the trap this decision has to avoid leaving behind, and the reason
every place that explains the number is rewritten in this change rather than left to read plausibly and mean
something else. The old reason, "matches the two languages `en` and `pl` the Dockerfile pre-caches", is false in both
halves after this change.

The capability this cap is sized against is strictly larger than before: today two languages stay resident, after
this change ten do.

### Decision 5: the image bakes the pair the settings name

The Dockerfile's warm-up currently names two languages:

```dockerfile
RUN DISABLE_AUTO_LOGGING_CONFIG=1 python3.11 -c "from paddleocr import PaddleOCR; PaddleOCR(lang='en', enable_mkldnn=False); PaddleOCR(lang='pl', enable_mkldnn=False)"
```

Naming languages there was already a way for the image and the service to disagree, and after Decision 2 it would be
a way for the image to bake a pair the service never loads, because the builder would resolve `lang='en'` through
the library while the service resolves it through its own settings. So the warm-up reads the settings the service
reads:

```dockerfile
RUN DISABLE_AUTO_LOGGING_CONFIG=1 python3.11 -c "from src.config.config import settings; from paddleocr import PaddleOCR; PaddleOCR(text_detection_model_name=settings.OCR_TEXT_DETECTION_MODEL, text_recognition_model_name=settings.OCR_TEXT_RECOGNITION_MODEL, enable_mkldnn=False)"
```

The builder stage already copies `src/` before this line and installs the project, so `src.config.config` imports and
every setting has a default. An operator who overrides the pair at run time still gets the old download-on-first-use
behaviour, which is the same trade as a language outside the pre-cached set today.

The auxiliary models in the pipeline (`PP-LCNet_x1_0_doc_ori`, `UVDoc`, `PP-LCNet_x1_0_textline_ori`) are baked by
the same construction call, exactly as they are today. The only thing that changes is which detection and
recognition models come with them.

### Decision 6: what this makes narrower or wider in the sibling change's capabilities

`openspec/changes/stop-ocr-getting-stuck-on-large-jobs/` is not archived, so nothing in `openspec/specs/` needs
modifying. Two of its statements interact with this change and neither is contradicted:

- `ocr-memory-bounds` requires the detector's input to be bounded by configuration rather than by the caller. That
  requirement is about `text_det_limit_type` and `text_det_limit_side_len`, which this change does not touch, and it
  holds for whichever detector is loaded.
- Its memory model is fitted against `PP-OCRv5_server_det`. After this change that model is exact for `ru` and
  `korean` and conservative for everything else. A conservative ceiling still satisfies a requirement to have one.
  Reconciled on 2026-09-24: measured on the new pair, one A4 page at 300 dots per inch costs about 440 MB flat (Superseded 2026-09-25: measured as a Linux container's cgroup `memory.peak`, one A4 page at 300 dpi peaks at 1016 MiB, see `fix-ocr-page-resolution` design.md Decision 10.),
  against the model's 9,060 MB at 144 dots per inch and 44,847 MB at 300, so for every language but `ru` and `korean`
  the model is void rather than conservative. That is the account [read-long-documents](../read-long-documents/design.md)
  gives, and task 4.6 records its container measurement against it rather than beside it. The sibling change's own
  specs were rewritten on the same date so that none of its requirements rests on the fitted figures.

When that change is archived, the delta this change adds stands beside it rather than editing it.

### Decision 7: the eviction metric's label names what the key is

`ascendocr_engine_cache_evictions_total{language=...}` becomes `ascendocr_engine_cache_evictions_total{engine=...}`,
carrying `"<detection model>/<recognition model>"`. A rename is a contract change on a metric, so it was checked
rather than assumed: grep across `*.md`, `*.json`, `*.yaml` and `*.yml` in this repository finds no dashboard, no
alert rule, and no document that names the metric. The only references are the service, the metrics module, and one
test.

`ascendocr_engine_warmup_duration_seconds{language=...}` keeps its label. Warm-up is requested per language, by
`DEFAULT_LANGUAGE`, so the language is the honest label there.

### Decision 8: nothing else moves

Three things that a reader of this change might expect to see and will not find, each deliberately:

- `OCR_DETECTOR_MAX_SIDE` and `OCR_MAX_INFERENCE_PIXELS` keep their values and their handling. A smaller detector
  may well afford a larger input, and that is a decision with numbers the owner has not settled.
- `enable_mkldnn` stays `False`.
- `ENGINE_CACHE_MAX_SIZE` keeps the value 2 (Decision 4), `compose.yaml` keeps every value it sets, and no container
  is rebuilt or restarted by this change.

### Decision 9: what could not be verified here, and what settles it

The host cannot run an inference, so four things are unverified. Each is a task, with its command, in
[tasks.md](tasks.md).

| Unverified | Why it matters | What settles it |
|---|---|---|
| The suite passes against `paddleocr` 3.7.0 | The pin is the change | Install the new pin into the module venv, run the full gate |
| The result dictionary still carries `rec_texts`, `rec_scores`, `dt_polys` | `_extract_text_lines` reads those three keys; a rename would empty every response | One real inference through `/v1/ocr`, or e2e spec 2 |
| Polish diacritics survive the model swap | It is the one caller-visible risk, and the vendor claims an improvement | e2e spec 3, which asserts a character from `{ś, ż, ą, ę, ć, ó, ł, ń, ź}` |
| The memory and time the new pair actually cost | Every memory number in the docs is fitted against the old detector | `memory.peak` from the container's cgroup after one A4 page, and the per-page timing method from task 1.2 of the sibling change. The owner's measurement of 2026-09-24, about 440 MB and 4.1 s to 10.0 s a page, is already recorded in `read-long-documents` design.md, and this row's container reading confirms or moves that account rather than starting a second one. Moved 2026-09-25 by the container reading: 1016 MiB and 20.5 s for one A4 page, see `fix-ocr-page-resolution` design.md Decision 10 |

The unit suite mocks `PaddleOCR`, so it proves the service asks for the right models and caches them by the right
key. It cannot prove the library accepts those names or that the models read text. Only the last three rows above
can, and all three need a machine with memory to spare.

## Risks / Trade-offs

**The model names could be wrong.** They are not guessed: `PP-OCRv6_small_det` and `PP-OCRv6_small_rec` appear in
`paddlex/configs/modules/text_detection/` and `.../text_recognition/`, in
`paddlex/modules/text_{detection,recognition}/model_list.py`, and in `ALL_MODELS` in
`paddlex/inference/utils/official_models.py`, all read from the 3.7.2 wheel. A wrong name fails loudly at engine
construction, at startup, on the readiness probe, rather than silently.

**A first request in a language outside the family now downloads.** True today for every language except `en` and
`pl`, and after this change true for `ru` and `korean` only. Ten languages move from "downloads unless it is one of
two" to "already baked".

**Accuracy could regress on the owner's own documents even though the vendor's benchmark improves.** This is the
real risk and it is why the accuracy verification is a task rather than a claim. The rollback is two environment
variables back to a v5 pair, with no code change and no rebuild, which is a property the explicit selection bought.

**A running container with an old model cache pays a download on its first request after the upgrade.** Rebuilding
the image is the intended path and is the owner's to run.

## Migration Plan

1. Apply the pin, the code, the tests, and the documentation (this change).
2. Update the module's virtual environment to the new pin and run the gate.
3. Rebuild the image, which bakes the new pair. Owner's action.
4. Run the engine-bound end-to-end specs, one at a time, against the rebuilt stack, after choosing a scenario from
   `docs/E2E_RUN_SCENARIOS.md`.
5. Re-measure memory and per-page time, and update the numbers that are currently conservative.

Rollback at any point before step 3 is reverting the change. After step 3, an operator can set
`OCR_TEXT_DETECTION_MODEL=PP-OCRv5_server_det` and `OCR_TEXT_RECOGNITION_MODEL=en_PP-OCRv5_mobile_rec` and restart,
which returns the English path to exactly today's models without a rebuild, at the cost of a download since the
image no longer bakes them. That override is not a full return to today's behaviour: it gives all ten in-family
languages one recognition model, where 3.6.0 gave `en` its own and the seven Latin codes `latin_PP-OCRv5_mobile_rec`.
Reverting the change is what restores the per-language mapping.

## Open Questions

1. **Does the medium member earn its 2.6 times cost on the owner's documents?** Only measurable against real pages,
   and only worth asking once the small member's own accuracy is measured. Task 4.7.
2. **Does a 10.1 MB detector afford a larger `OCR_MAX_INFERENCE_PIXELS` or a higher `OCR_DETECTOR_MAX_SIDE`?**
   Deliberately out of scope here, and the first question worth asking once the memory re-measurement in task 4.6
   reports. The pixel ceiling half is answered: `fix-ocr-page-resolution` deletes `OCR_MAX_INFERENCE_PIXELS` and
   `OCR_DETECTOR_MAX_SIDE`, reads an oversized page shrunk, and owns the detector bound per quality mode, which also
   answers `read-long-documents` Open Question 5.
3. **Should `SUPPORTED_LANGUAGES` widen now that one model covers 50 languages?** The allowlist currently costs a
   caller nine Latin languages the loaded model can already read. Widening it is free in memory under the new cache
   key, which is a real argument, and it still needs someone to decide which codes the service promises.
