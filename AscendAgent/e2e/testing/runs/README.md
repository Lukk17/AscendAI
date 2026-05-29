# e2e test runs

Each manual e2e test run drops a filled-in copy of the matching `*-tasks.template.md` here, named
`<UTC-timestamp>_<N>-<feature>-tasks.md`.

---

### Contract

1. Specs (`AscendAgent/e2e/testing/<N>-<feature>-test.md`) are **immutable** between runs. The runner never edits
   them.
2. Templates (`AscendAgent/e2e/testing/templates/<N>-<feature>-tasks.template.md`) are also **immutable**. They
   define the checkbox list for that test.
3. Each run starts by copying the relevant template from `../templates/` into this directory with a UTC timestamp
   prefix. The runner ticks boxes as it completes each step and fills in **Result summary** and **Additional tasks I
   did** at the end.

---

### Naming

```text
2026-05-12T18-15-00_1-weather-mcp-tasks.md
2026-05-12T18-15-00_2-image-description-tasks.md
2026-05-12T18-15-00_3-summarization-tasks.md
2026-05-12T18-15-00_4-semantic-memory-tasks.md
2026-05-12T18-15-00_5-rag-tasks.md
```

Use ISO-8601 UTC with colons replaced by hyphens so the filename is filesystem-safe across Windows / macOS / Linux.
Group all five tests from one sweep under the same timestamp; one timestamp = one full e2e sweep.

---

### What the AI runner does

1. Read the spec for the test.
2. Copy the template from [../templates/](../templates/) into [runs/](.) with a timestamped filename.
3. **Record `Start (UTC)`** as the very first action. The wall-clock instant *before* the prerequisite checks begin.
4. Execute each task in order. Tick the box on success; record what went wrong on failure.
5. After the **Verdict** line is decided, **record `End (UTC)`**. The wall-clock instant *after* the last
   verification step.
6. Compute `Duration = End - Start` and record it as `HH:MM:SS`. **This is total wall-clock for the test**, not just
   the Bruno request duration. A Bruno call may take 5 s while the full test (prereqs + reset + run + verify) takes
   2 minutes. The duration field captures the latter.
7. Fill in **Input tokens** and **Output tokens** with your best estimate of the LLM API tokens consumed across the
   run. Leave blank if you can't get exact numbers. Don't invent.
8. Write the **Result summary** paragraph and the **Verdict** (PASS or FAIL).
9. If any step was done outside the spec (extra diagnostics, retries, manual inspection), log it under **Additional
   tasks I did**.

---

### Keeping or wiping run records

Each run record is a snapshot of what happened. Either commit them under a `runs/<date>/` subfolder for an audit
trail, or treat them as ephemeral and gitignore the directory contents; both are fine. Default: this README is
tracked, individual run files are not (see `.gitignore`).
