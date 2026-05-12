# e2e test runs

Each manual e2e test run drops a filled-in copy of the matching `*-tasks.template.md` here, named `<UTC-timestamp>_<N>-<feature>-tasks.md`.

## Contract

1. Specs (`AscendAgent/e2e/testing/<N>-<feature>-test.md`) are **immutable** between runs. The runner never edits them.
2. Templates (`AscendAgent/e2e/testing/<N>-<feature>-tasks.template.md`) are also immutable — they define the checkbox list for that test.
3. Each run starts by copying the relevant template into this directory with a UTC timestamp prefix. The runner ticks boxes as it completes each step and fills in **Result summary** and **Additional tasks I did** at the end.

## Naming

```
2026-05-12T18-15-00_1-weather-mcp-tasks.md
2026-05-12T18-15-00_2-image-description-tasks.md
2026-05-12T18-15-00_3-summarization-tasks.md
2026-05-12T18-15-00_4-semantic-memory-tasks.md
2026-05-12T18-15-00_5-rag-tasks.md
```

Use ISO-8601 UTC with colons replaced by hyphens so the filename is filesystem-safe across Windows / macOS / Linux. Group all five tests from one sweep under the same timestamp; one timestamp = one full e2e sweep.

## What the AI runner does

1. Read the spec for the test.
2. Copy the template into `runs/` with a timestamped filename.
3. Execute each task in order. Tick the box on success; record what went wrong on failure.
4. After the **Run** section completes, fill in **Result summary** (one paragraph) and **Verdict** (PASS / FAIL).
5. If any step was done outside the spec (extra diagnostics, retries, manual inspection), log it under **Additional tasks I did**.

## Keeping or wiping run records

Each run record is a snapshot of what happened. Either commit them under a `runs/<date>/` subfolder for an audit trail, or treat them as ephemeral and gitignore the directory contents — both are fine. Default: this README is tracked, individual run files are not (see `.gitignore`).
