# Contracts

Consumer-driven contract files shared between AscendAI services. Each file records what one service (the consumer) expects from another (the provider), and both sides test against the same committed copy.

---

### What is here

| File | Consumer | Provider | Format |
|---|---|---|---|
| `pacts/ascend-agent-ascend-ocr.json` | `ascend-agent` | `ascend-ocr` | Pact specification V4 |

The pact covers the REST calls that `AscendOcrClient` in ascend-agent makes to ascend-ocr. It does not cover the ascend-ocr MCP tools, because the agent does not call them.

The decision behind this setup is [ADR-M010](../docs/architecture/decisions/ADR-M010-consumer-driven-contract-in-repo.md).

---

### Who writes the pact

The consumer test `com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrClientPactTest` in `apps/ascend-agent` writes `pacts/ascend-agent-ascend-ocr.json` every time `./gradlew test` runs in that module. It uses Pact JVM and needs no running service and no Docker.

Nobody edits the JSON file by hand. Change the consumer test, regenerate the file, and commit both in the same commit.

---

### Who reads the pact

The provider test `tests/contract/test_ascend_agent_pact.py` in `apps/ascend-ocr` reads the committed file with pact-python and replays every interaction against the ascend-ocr application. A change on the ascend-ocr side that breaks what the agent expects fails that test.

---

### Regenerate the pact

Run these from the repository root. Go to the agent module first:

```bash
cd apps/ascend-agent
```

Then run the consumer test. PowerShell:

```powershell
.\gradlew.bat --no-daemon test --tests "com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrClientPactTest"
```

Unix shell:

```bash
./gradlew --no-daemon test --tests "com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrClientPactTest"
```

Commit the updated `contracts/pacts/ascend-agent-ascend-ocr.json` together with the change that caused it. `.gitattributes` keeps the file on LF line endings, so a Windows checkout and the Linux CI runner produce the same bytes.

---

### Check for drift

After regenerating, this command must print nothing. Any output means the committed pact no longer matches what the consumer test produces:

```bash
git status --porcelain -- contracts/pacts
```

CI runs the same check in the `contract-consumer` job and fails when it prints anything.

---

### Verify the provider locally

Go to the OCR module:

```bash
cd apps/ascend-ocr
```

Then run the provider test through the module's own virtual environment. PowerShell:

```powershell
.venv/Scripts/python.exe -m pytest tests/contract --no-cov
```

Unix shell:

```bash
.venv/bin/python -m pytest tests/contract --no-cov
```

`--no-cov` is needed because the module's pytest settings enforce 100 percent coverage, which a run of the contract tests alone cannot reach.

---

### Usage tracking is off

Both Pact libraries send anonymous usage events to Google Analytics unless tracking is turned off. Pact JVM does it from the consumer test, and the Rust core that pact-python 3.4.0 loads through `pact_ffi` does it from the provider verification. Both read the environment variable `PACT_DO_NOT_TRACK` and stop when it is `true`.

- The consumer test needs nothing from you. The `test` task in `apps/ascend-agent/build.gradle.kts` sets the system property `pact_do_not_track` to `true`.
- Both CI jobs, `contract-consumer` and `contract-provider`, set `PACT_DO_NOT_TRACK` to `true`.
- For a local provider run, set the variable in the same shell before running the provider test. PowerShell:

```powershell
$env:PACT_DO_NOT_TRACK = "true"
```

Unix shell:

```bash
export PACT_DO_NOT_TRACK=true
```

---

### In CI

Two jobs in `.github/workflows/ci.yaml` run the contract, in order: `contract-consumer` regenerates the pact and fails on drift, then `contract-provider` verifies the committed pact against ascend-ocr. Both run when ascend-agent, ascend-ocr, `contracts/` or the workflows change. The details are in [.github/workflows/README.md](../.github/workflows/README.md).

---

### No Pact Broker

There is no Pact Broker. The committed file is the only copy of the contract, and git history is its version history. That means there is no `can-i-deploy` check either: nothing records which ascend-agent version was verified against which ascend-ocr version. The contract proves that the two sides agree at the same commit. It does not prove that two images released separately from different commits work together.
