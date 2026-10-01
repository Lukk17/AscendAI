Not started. Start only after `enhance-web-search-crawl-at-scale`, `add-document-connectors` and
`add-document-management-api` are archived. Commands run from `apps/ascend-agent/`.

## 1. Connector

- [ ] 1.1 Add the `web` connector configuration (seeds, patterns, depth, page budget, schedule) under
      `src/main/java/com/lukk/ascend/ai/agent/service/connector/web/`, validated with Bean Validation. Verify with a
      unit test for each bound.
- [ ] 1.2 Add a crawl client for the four `/api/v1/crawl/jobs` operations with timeouts. Verify with a WireMock test
      for submit, poll to `succeeded`, poll to `failed` and cancel on deadline.
- [ ] 1.3 Implement D1: copy new and changed pages into the tenant prefix and trigger ingestion. Verify with an
      integration test (Testcontainers object storage) that landed keys sit under the tenant prefix only.
- [ ] 1.4 Implement D3. Verify a page missing on the second run is deleted and recorded `DELETED`.

## 2. Documentation and verification

- [ ] 2.1 Add the web connector section to `docs/CONNECTORS.md`. Verify it lists every configuration field.
- [ ] 2.2 Run `./gradlew test` and `./gradlew integrationTest` (`.\gradlew.bat` on Windows). Verify both pass.
