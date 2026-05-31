# e2e test runs

Each AscendWebSearch e2e test run drops a filled-in copy of the matching `*-tasks.template.md` here, named
`<UTC-timestamp>_<N>-<capability>-tasks.md`. This README is tracked; the run files themselves are gitignored by
default.

## Contract

1. Specs (`../<N>-<capability>-test.md`) are **immutable** between runs. The runner never edits them.
2. Templates (`../templates/<N>-<capability>-tasks.template.md`) are also **immutable**. They define the checkbox
   list for that test.
3. Each run starts by copying the relevant template from `../templates/` into this directory with a UTC timestamp
   prefix. The runner ticks boxes as it completes each step and fills in **Result summary** and **Additional tasks I
   did** at the end.

## Naming

```text
2026-05-30T01-15-00_1-invalid-input-tasks.md
2026-05-30T01-15-00_2-search-happy-path-tasks.md
2026-05-30T01-15-00_3-read-example-com-tasks.md
```

Use ISO-8601 UTC with colons replaced by hyphens so the filename is filesystem-safe across Windows / macOS / Linux.
Group all tests from one sweep under the same timestamp; one timestamp = one full e2e sweep.

## Runner steps

1. Read the spec for the test.
2. Copy the template from [../templates/](../templates/) into [runs/](.) with a timestamped filename.
3. **Record `Start (UTC)`** as the very first action. Wall-clock instant *before* the prerequisite checks begin.
4. Execute each task in order. Tick the box on success; record what went wrong on failure.
5. After the **Verdict** line is decided, **record `End (UTC)`**. Wall-clock instant *after* the last verification
   step.
6. Compute `Duration = End - Start` and record it as `HH:MM:SS`. **Wall-clock for the whole test** (prereqs + reset +
   run + verify), NOT just the Bruno request duration.
7. Fill **Input tokens** and **Output tokens** with your best estimate of the LLM tokens consumed across the run.
   AscendWebSearch tests do not invoke any LLM — leave these as 0.
8. Write the **Result summary** paragraph and the **Verdict** (PASS or FAIL).
9. If any step was done outside the spec (extra diagnostics, retries, manual inspection), log it under
   **Additional tasks I did**.

## Gitignore policy

Run record files are ephemeral by default (gitignored). This README is kept tracked. Promote individual runs to a
committed audit trail by moving them under `runs/<YYYY-MM>/` subfolders if desired.
