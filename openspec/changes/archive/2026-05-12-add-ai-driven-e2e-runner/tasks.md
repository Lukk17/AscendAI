> **SUPERSEDED** — see `proposal.md` banner. The simpler in-spec-assertion architecture shipped in commits `c791cc5` and `2edcbee` made every task below unnecessary. Items are preserved here as audit trail of "what we considered and decided no", not as work-still-to-do.

## 1. Author the tracked judge prompt

- [ ] 1.1 Create `AscendAgent/e2e/judge-prompt.md`. Sections required: (a) **Role** ("you are a strict end-to-end test judge"), (b) **Rubric** with PASS / FAIL / INCONCLUSIVE definitions matching design D6, (c) **Output schema** showing the exact JSON shape from D2, (d) **Evidence-citation rule** ("evidence_cited MUST contain a verbatim substring from the supplied response or log"), (e) **Two worked examples** (one PASS — semantic memory recall; one FAIL — RAG retrieval missing), (f) **Inconclusive triggers** (closed list: `pre_flight_unreachable`, `log_unreadable`, `judge_disagreement`, `judge_unparseable`, `evidence_truncated`)
- [ ] 1.2 Add a top-of-file warning: "DO NOT edit casually — this prompt's sha is recorded in every run output. Edits change historical comparability. Treat as production code."
- [ ] 1.3 Verify the prompt parses correctly by hand-feeding it (with a synthetic evidence bundle for one PASS and one FAIL case) to Haiku 4.5 at temperature 0; verdict matches expectation; response is valid JSON.
- [ ] 1.4 Verify the same against Gemini Flash to confirm the prompt is portable across the supported judge models from D8.
- [ ] 1.5 Pin the recommended judge model list in the prompt header: Haiku 4.5 (default), Gemini 3.1 Flash (alt), GPT-5-mini (alt).

## 2. Author the doc convention

- [ ] 2.1 Create `AscendAgent/e2e/testing/CONVENTIONS.md` describing the machine-executable shape from design D3: required headings (`### Pre-flight`, `### Test N — <name>`, `**Pass:**`), the canonical-bash-block rule, multi-criterion bullet structure, side-effect-block opt-in, where logs come from
- [ ] 2.2 Include a do/don't list (do: one bash block per step. don't: split a request across two blocks. do: list each pass criterion as a bullet. don't: chain multiple criteria with "and" inside one sentence — the runner can't split them reliably)
- [ ] 2.3 Include a minimal worked example of a 1-test capability doc following the convention
- [ ] 2.4 Cross-link from `AscendAgent/e2e/testing/README.md` ("see CONVENTIONS.md before adding a test")

## 3. Normalize existing test docs

- [ ] 3.1 `AscendAgent/e2e/testing/semantic-memory.md`: confirm `### Pre-flight` / `### Test 1 — Write` / `### Test 2 — Recall` / `**Pass:**` shape; convert any prose pass criterion into bullets; ensure each bash block is self-contained
- [ ] 3.2 `AscendAgent/e2e/testing/rag.md`: same normalization
- [ ] 3.3 `AscendAgent/e2e/testing/pdf-read.md`: same normalization
- [ ] 3.4 `AscendAgent/e2e/testing/image-description.md`: same normalization
- [ ] 3.5 `AscendAgent/e2e/testing/weather-mcp.md`: same normalization
- [ ] 3.6 No behavioral change — the same human steps produce the same outcome. The change is shape-only.

## 4. Manually drive the runner workflow once

- [ ] 4.1 Stand up the local stack (`docker-compose up -d` for prerequisites, `./gradlew bootRun` for AscendAgent)
- [ ] 4.2 In a fresh Claude Code session, open `AscendAgent/e2e/testing/semantic-memory.md` and CONVENTIONS.md and judge-prompt.md
- [ ] 4.3 Drive Claude through: read pre-flight, run pre-flight commands, run Test 1 bash block, capture response + 30s log slice, build the evidence bundle per design D4, send judge call with judge-prompt.md as system prompt, parse JSON response, repeat for Test 2
- [ ] 4.4 Verify judge verdict matches the expected outcome (both tests should PASS on a healthy stack)
- [ ] 4.5 Assemble the run output following the format from spec scenarios — frontmatter (judge prompt sha, judge model, runner version, doc sha, UTC timestamp), per-test verdicts with evidence_cited, overall verdict
- [ ] 4.6 Save the output to `AscendAgent/e2e/runs/sample-semantic-memory.md` and check it in as the regression fixture
- [ ] 4.7 Add `AscendAgent/e2e/runs/.gitkeep` so the folder is tracked even when empty

## 5. Verify failure-mode coverage

- [ ] 5.1 With AscendAgent stopped, run pre-flight only — confirm runner produces `INCONCLUSIVE` overall with reason `pre_flight_unreachable`
- [ ] 5.2 Inject a deliberate fail: send `prompt=My name is Luke` to the wrong user_id, then ask the recall test as the original user — confirm runner produces `FAIL` on Test 2 with evidence_cited quoting the absence of memory items in the agent log
- [ ] 5.3 Force a judge disagreement: set the judge model to a higher-temperature alternative, run the same step twice — confirm the retry path triggers and the verdict comes back `INCONCLUSIVE` with reason `judge_disagreement` (only if reproducible; otherwise document as a follow-up)
- [ ] 5.4 Force a cost abort: temporarily set `--max-cost-usd 0.001` and confirm the runner aborts with a partial run output marked `ABORTED`

## 6. Cost-cap behavior

- [ ] 6.1 Implement the pre-run cost estimate as part of the runner workflow in CONVENTIONS.md (formula from design D7)
- [ ] 6.2 WARN threshold $0.05: print `[e2e-runner] WARNING: estimated cost $X.XX exceeds $0.05` and require explicit confirmation if interactive
- [ ] 6.3 ABORT threshold $0.50 (override `--max-cost-usd`): runner stops after the in-flight criterion, writes partial output marked `ABORTED`, exits non-zero
- [ ] 6.4 Document in `judge-prompt.md` header that cost cap is a runaway-loop fuse, not a budget tool

## 7. Run output format

- [ ] 7.1 Define the run output template in CONVENTIONS.md: YAML frontmatter (`judge_prompt_sha`, `judge_model`, `runner_version`, `test_doc_sha`, `started_at_utc`, `finished_at_utc`, `overall_verdict`, `aborted: bool`), then per-test sections (`## Test 1 — Write`, with verdict, evidence excerpts, judge reasoning), then a `## Inconclusive section` only if any criteria were inconclusive
- [ ] 7.2 Truncation marks: when response/log is truncated, the run output writes `... [truncated, original size: N bytes]` so a reviewer can spot lost evidence
- [ ] 7.3 Filename: `<UTC-yyyymmdd-hhmmss>-<capability>.md` (e.g. `20260507-143012-semantic-memory.md`)

## 8. Optional skill packaging

- [ ] 8.1 (Optional) Create `.agents/skills/e2e-runner/SKILL.md` that codifies steps 4.2–4.7 as a reusable skill any agent can invoke
- [ ] 8.2 (Optional) Skill arg surface: `--capability <name>`, `--judge-model <id>`, `--max-cost-usd <n>`, `--no-confirm`
- [ ] 8.3 (Optional) Skill output: prints the path of the run output file as the final line for downstream tooling to capture

## 9. Documentation

- [ ] 9.1 Update `AscendAgent/e2e/testing/README.md` with a "Run via AI" section: 3-step quickstart pointing at CONVENTIONS.md and judge-prompt.md
- [ ] 9.2 Cross-link from `docs/testing/README.md` (if it covers the suite) and `AscendAgent/AGENTS.md` "Relevant Skills" if the skill is created
- [ ] 9.3 Add a one-paragraph mention in the root `README.md` Documentation section so contributors find the runner

## 10. Verification

- [ ] 10.1 Run the full suite (5 capabilities) end-to-end via the runner against a healthy local stack; expect 5 × `PASS` overall verdicts
- [ ] 10.2 Run the full suite with AscendMemory stopped; expect `semantic-memory` and `rag` to come back `INCONCLUSIVE` (memory unreachable), other three `PASS`
- [ ] 10.3 Confirm every run output captures the judge prompt sha + model + doc sha (open three sample outputs and check the frontmatter)
- [ ] 10.4 Confirm cost-cap WARN fires for a 5-capability run (full suite cost estimate > $0.05 default warn threshold)
- [ ] 10.5 Update `openspec/changes/add-ai-driven-e2e-runner/tasks.md` checkboxes as work proceeds
