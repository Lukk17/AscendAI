# ADR-M010: Consumer-Driven Contract Committed in the Repository

---

### Status

Accepted (2026-09-25)

---

### Context

ascend-agent calls ascend-ocr over REST through `AscendOcrClient`: it submits a document as a job, reads the job state, and deletes the job. The two services are written in different languages, built by different tools, and released as separate images. Until now the only things that tied them together were an OpenAPI file saved in the agent's test resources and agent tests that replay responses recorded from a running ascend-ocr at some earlier time. None of those checks the current provider code, so a change to ascend-ocr's response shape could merge while the agent still expected the old one.

Both services live in this one repository (ADR-M001), and CI already runs on every pull request. A contract check can therefore see both sides at the same commit.

---

### Decision

Use a consumer-driven contract with Pact, committed in the repository, with no Pact Broker.

- The format is Pact specification V4.
- The consumer side is Pact JVM 4.6.21. The consumer test `AscendOcrClientPactTest` in `apps/ascend-agent` writes `contracts/pacts/ascend-agent-ascend-ocr.json` whenever `./gradlew test` runs. The 4.6 line is used because it is built against the Kotlin standard library that Spring Boot 3.5.14 manages. The 4.7.x line is built with Kotlin 2.3, which does not fit that managed version.
- The provider side is pact-python 3.4.0. The test `tests/contract/test_ascend_agent_pact.py` in `apps/ascend-ocr` reads the committed file and replays every interaction against the ascend-ocr application.
- The pact file is committed. Git is its storage and its version history. `.gitattributes` keeps it on LF line endings so Windows and Linux produce the same bytes.
- CI runs two ordered jobs in `.github/workflows/ci.yaml`. `contract-consumer` regenerates the pact and fails when the regenerated file differs from the committed one. `contract-provider` then verifies the committed file against ascend-ocr. Both run when either service, `contracts/`, or the workflows change.

The operating details are in [contracts/README.md](../../../contracts/README.md).

---

### Alternatives Considered

#### Alternative 1: A Pact Broker

- Pros: Records which consumer version was verified against which provider version. Enables `can-i-deploy`, which answers whether a given pair of released versions is safe to run together. Supports webhooks that start provider verification when a pact changes.
- Cons: One more service to host, secure, back up and keep running, or a paid hosted one. CI would need a broker token, and `ci.yaml` today uses no secrets at all, which is what makes fork pull requests safe. With both services in one repository, the broker would mostly store what git already stores.
- Why not: The cost is a new piece of infrastructure and the first CI secret, and the main benefit, `can-i-deploy` across independent release lines, is not something this project needs today.

#### Alternative 2: Diff a saved OpenAPI file

- Pros: No new library. ascend-ocr already publishes an OpenAPI document, and the agent already keeps a copy in its test resources.
- Cons: The OpenAPI document describes everything the provider offers, not what the consumer actually uses, so a harmless change to an unused field fails the diff while a change in behaviour that the schema does not express passes it. It checks the description of the interface, not the running provider. Someone still has to refresh the saved copy by hand.
- Why not: It tests the wrong thing. A consumer-driven contract fails exactly when the agent's real expectations break, and passes otherwise.

---

### Consequences

- Positive: A change on either side that breaks what the agent expects from ascend-ocr fails CI on the pull request that made it.
- Positive: No new infrastructure and no secret in CI.
- Positive: The contract is reviewed in the same pull request as the code that changed it, because the regenerated JSON is part of the diff.
- Negative: There is no `can-i-deploy`. Nothing records which agent version was verified against which OCR version.
- Negative: The images are released separately (see `.github/workflows/README.md`). The contract proves that both sides agree at the same commit, not that an agent image built from one commit works with an OCR image built from another.
- Negative: The MCP surface of ascend-ocr is not covered, because the agent does not use it. A change to the MCP tools is not checked by this contract.
- Negative: A developer who changes the consumer test must regenerate and commit the pact, or the drift check fails.

#### Risks

- Pact JVM has to stay on the 4.6 line while the managed Kotlin version stays where Spring Boot 3.5.x puts it. A dependency update that moves to 4.7.x breaks the build rather than failing silently, which is the safe direction.
- If the consumer test writes anything that changes between runs, such as a timestamp or a tool version, the drift check fails on every run. The consumer test must produce the same bytes for the same code.
