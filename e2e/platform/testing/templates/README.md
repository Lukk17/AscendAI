# e2e run-record templates

One tasks template per spec. Each is the checkbox template the runner copies into the runs directory at the start of every execution.

## Relationship to the specs

The specs themselves live one level up, directly under testing. This templates directory holds only the run-record templates that mirror them, one template per spec, sharing the same number prefix and capability name.

## Contract

1. Templates are immutable between runs. The runner never edits them in place.
2. Each template mirrors its spec Prerequisites, Reset, Run, and Expected items as checkboxes, plus a Verdict checkbox, a Result summary block with Input tokens, Output tokens, Start in UTC, End in UTC, and Duration, and an Additional tasks I did section.
3. To run a test, copy the matching template into the runs directory with a UTC-timestamp prefix, then tick boxes and fill results in that copy, never here.

See the runs guide for the full runner contract.

## Neighbours

- [e2e/platform/README.md](../../README.md)
- [e2e/platform/fixtures/README.md](../../fixtures/README.md)
- [e2e/platform/testing/README.md](../README.md)
- [e2e/platform/testing/runs/README.md](../runs/README.md)
