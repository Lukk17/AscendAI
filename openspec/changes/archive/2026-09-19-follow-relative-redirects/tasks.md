Every command runs from `apps/ascend-web-hunter/` through that module's own virtual environment
(`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux and macOS), never the system Python, and
through the `python -m <tool>` form. The gate is `--cov=src --cov-branch --cov-report=term-missing
--cov-fail-under=100`, so every branch added below needs a test before the suite goes green. Tests are written with
the code, not after it.

## 1. Relative redirect resolution

- [x] 1.1 Track the URL of the hop that produced the current response in `fetch_with_curl_cffi`, and resolve each
      `Location` against it with `urljoin` before it reaches `pin_safe_host`. Verify a root-relative `/article` is
      requested as an absolute URL on the same host and the content is returned.
- [x] 1.2 Verify a path-relative `../index.html` resolves against the previous hop rather than the URL the read
      started from, using a two-hop chain whose two bases differ.
- [x] 1.3 Verify a protocol-relative `//host/page` takes the scheme of the hop that returned it, is validated as
      that second host, and carries that host's own pin.
- [x] 1.4 Verify the guard is unchanged for a relative hop: a protocol-relative `Location` onto a host that
      resolves to a link-local address is refused with no request issued for it, and a relative `Location` whose
      own host has rebound to an internal address between the first hop and the second is refused too.
- [x] 1.5 Name the resolved URL and the hop it came from in the refusal log, so the message says where the fetch
      was headed rather than only what the header said.

## 2. Specification correction

- [x] 2.1 Rewrite the `SSRF guard re-validated on every redirect hop` requirement as a `MODIFIED` delta: drop the
      response-history sentence, state that re-validation happens before each hop is fetched and why no history is
      available to inspect, and fold in relative-reference resolution as a step in validating a hop.
- [x] 2.2 Add the three scenarios that carry the new behaviour, keeping the existing three unchanged.
- [x] 2.3 Remove the sentence in ADR-012's context that says `validate_redirect_chain` re-checks a response
      history, since the helper is no longer in the repository. The decision the ADR records is untouched.
- [x] 2.4 Add the relative-resolution sentence to the arc42 crosscutting SSRF section, next to the per-hop check it
      belongs to.

## 3. Verification gate

- [x] 3.1 `python -m ruff check .` clean, with no new suppression anywhere.
- [x] 3.2 `python -m ruff format --check .` clean.
- [x] 3.3 `python -m mypy src` clean, with no new `type: ignore`.
- [x] 3.4 `python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` green.
- [x] 3.5 Live check against the running service on `http://localhost:7021`: a page that redirects relatively is
      read, and the response `mode` names a curl_cffi tier instead of escalating past it.
- [x] 3.6 `openspec validate follow-relative-redirects --strict` and `openspec validate --all --strict` pass.
