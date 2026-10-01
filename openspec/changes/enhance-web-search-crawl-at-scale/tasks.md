Every command runs from `apps/ascend-web-hunter/` through `.venv/Scripts/python.exe -m <tool>` (Windows) or
`.venv/bin/python -m <tool>` (Linux and macOS). The gate is
`python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`.

## 1. Configuration and dependencies

- [ ] 1.1 Add the S3 client and `protego` to `pyproject.toml` with exact pins. Verify `python -m pip install -e ".[dev]"`.
- [ ] 1.2 Add every setting in `design.md` D2, D3, D5 and D7 to `src/config/config.py`. Verify with cases in
      `tests/config/test_config.py`.
- [ ] 1.3 Add the `CRAWL_RESULT_S3_*` variables to `compose.ascend-web-hunter.yaml`, the root `.env.example`,
      `deploy-standalone/compose.yaml`, `deploy-standalone/.env.example` and the standalone README table in the same
      commit. Verify `docker compose config` from the repository root succeeds.

## 2. Job model and API

- [ ] 2.1 Create `src/crawl/models.py` with the D2 request model (Pydantic, every bound a `Field` constraint) and the job
      record. Verify with tests for each bound and for regular-expression syntax being treated as a literal glob.
- [ ] 2.2 Create `src/api/rest/crawl_endpoints.py` with the four D1 endpoints and mount it in `src/main.py`. Verify
      with tests for 202, 200, 404 `JOB_NOT_FOUND` and cancel.
- [ ] 2.3 Add `crawl_submit`, `crawl_job_status`, `crawl_list_jobs` and `crawl_cancel_job` to `src/api/mcp/mcp_server.py`.
      Verify with tests that each returns the same fields as its REST twin.

## 3. SSRF rules

- [ ] 3.1 Check every seed at submission per D4. Verify with tests that `http://127.0.0.1/`, `http://10.0.0.1/`,
      `file:///etc/passwd`, `https://user:pass@example.com/` and a hostname resolving to a private address each get HTTP
      400 `UNSAFE_URI` and create no job.
- [ ] 3.2 Route discovered links, redirect hops, robots.txt and sitemap fetches through the guard and pinning. Verify a
      link to a private address is dropped and counted as `skipped_unsafe`.

## 4. Frontier, workers and politeness

- [ ] 4.1 Create `src/crawl/frontier.py` per D5. Verify with a fake Redis that two workers never claim the same URL and
      the per-domain cap holds.
- [ ] 4.2 Create `src/crawl/robots.py`. Verify a disallowed path is not fetched, `Crawl-delay` is honoured, sitemap URLs
      seed the frontier, and `respect_robots=false` is refused for a domain not in `CRAWL_ROBOTS_OPT_OUT_DOMAINS`.
- [ ] 4.3 Create `src/crawl/worker.py` reading each page through `WebReader` and honouring depth, patterns,
      `same_domain_only` and `page_budget`. Verify with a fixture site served by a local test server.

## 5. Results and recrawl

- [ ] 5.1 Create `src/crawl/result_store.py` per D3. Verify with a stubbed S3 client that keys carry the prefix and the
      NDJSON lines match the pages.
- [ ] 5.2 Implement D6. Verify a 304 and an equal hash both write no page file and mark the page `unchanged`.

## 6. Proxy hook

- [ ] 6.1 Add `CRAWL_PROXY_URL` to `src/proxy/proxy_provider.py` per D7 and the MODIFIED requirement in
      `specs/web-search-antibot-evasion/spec.md`. Verify a crawl uses it and a single read does not.

## 7. Documentation and verification

- [ ] 7.1 Update `AGENTS.md`, `README.md` and `docs/configuration.md` with the API, the settings, the SSRF rules and the
      honest scale statement. Write ADR-018 for the crawl model. Verify every setting appears in all three files.
- [ ] 7.2 Bump the version with one CHANGELOG entry. Verify `pyproject.toml` and the CHANGELOG agree.
- [ ] 7.3 Run the gate, `python -m ruff check .` and `python -m mypy src`. Verify all pass with no suppression.
- [ ] 7.4 With the stack up, crawl a small public documentation site with `page_budget` 10 and confirm the job reaches
      `succeeded`, `pages.ndjson` exists in Floci under the prefix, and a second run marks unchanged pages. Verify by
      reading the objects back from Floci.
