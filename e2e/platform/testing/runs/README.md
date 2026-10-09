# e2e test runs

Each platform e2e test run drops a filled-in copy of the matching tasks template here, named with a UTC timestamp prefix. This README is tracked. The run files themselves are gitignored by default.

## Contract

1. Specs in the testing directory are immutable between runs. The runner never edits them.
2. Templates in the templates directory are also immutable. They define the checkbox list for that test.
3. Each run starts by copying the relevant template from the templates directory into this directory with a UTC timestamp prefix. The runner ticks boxes as it completes each step and fills in Result summary and Additional tasks I did at the end.

## Naming

```text
2026-05-30T01-15-00_1-metrics-and-targets-tasks.md
```

```text
2026-05-30T01-15-00_2-logs-reach-loki-tasks.md
```

Use ISO-8601 UTC with colons replaced by hyphens so the filename is filesystem-safe across Windows, macOS, and Linux. Group all tests from one sweep under the same timestamp. One timestamp equals one full e2e sweep.

## Runner steps

1. Read the spec for the test.
2. Copy the template from the templates directory into this directory with a timestamped filename.
3. Record Start in UTC as the very first action. Wall-clock instant before the prerequisite checks begin.
4. Execute each task in order. Tick the box on success. Record what went wrong on failure.
5. After the Verdict line is decided, record End in UTC. Wall-clock instant after the last verification step.
6. Compute Duration as End minus Start and record it as hours, minutes, and seconds. Wall-clock for the whole test, including prerequisites, reset, run, and verification, not just the Bruno request duration.
7. Fill Input tokens and Output tokens with the best available estimate. Leave blank when unavailable rather than inventing a number.
8. Write the Result summary paragraph and the Verdict with PASS or FAIL.
9. If any step was done outside the spec, log it under Additional tasks I did.

## Gitignore policy

Run record files are ephemeral by default and gitignored. This README is kept tracked. Promote individual runs to a committed audit trail by moving them under runs subfolders named by year and month if desired.

## Neighbours

- [e2e/platform/README.md](../../README.md)
- [e2e/platform/fixtures/README.md](../../fixtures/README.md)
- [e2e/platform/testing/README.md](../README.md)
- [e2e/platform/testing/templates/README.md](../templates/README.md)
