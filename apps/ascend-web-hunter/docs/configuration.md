# Configuration

Every settings field is bound through [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
against environment variables and `.env`. The source of truth is
[src/config/config.py](../src/config/config.py); this table is for quick lookup.

---

### API and server

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `API_PORT` | `7021` | Service port |
| `API_HOST` | `0.0.0.0` | Bind address (deliberately broad for the container case) |
| `LOG_LEVEL` | `INFO` | `DEBUG | INFO | WARNING | ERROR | CRITICAL` |

---

### SearXNG (meta-search)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `SEARXNG_BASE_URL` | `http://localhost:9020` | SearXNG host; Docker network sees `http://searxng:8080` |
| `SEARXNG_USER_AGENT` | `ascend-web-hunter/1.0` | Forwarded to SearXNG |
| `SEARXNG_X_REAL_IP` | `127.0.0.1` | `X-Real-IP` sent upstream |
| `SEARXNG_X_FORWARDED_FOR` | `127.0.0.1` | `X-Forwarded-For` sent upstream |

---

### Blocklist and content validation

The blocklist is loaded from disk at startup and never downloaded automatically. `BLOCKLIST_PATH` points at the
file vendored into the repository and the container image (`src/assets/fanboy-annoyance.txt`); a missing or
corrupt file there is a packaging defect and the service refuses to start. `BLOCKLIST_URL` is only reached by
`POST /api/v1/blocklist/refresh`, an explicit operator action — see
[the architecture decision record](architecture/decisions/ADR-008-blocklist-vendored-not-fetched.md).

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `BLOCKLIST_URL` | `https://secure.fanboy.co.nz/fanboy-annoyance.txt` | Source `POST /api/v1/blocklist/refresh` downloads from |
| `BLOCKLIST_PATH` | `src/assets/fanboy-annoyance.txt` | Path to the vendored blocklist file; also where a refresh writes |
| `BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS` | `60.0` | Minimum seconds between accepted refresh attempts; a call inside the window gets 429 |
| `VALIDATION_MIN_WORDS` | `10` | Minimum word count for a tier's output to count as success |
| `MIN_FLESCH_SCORE` | `20.0` | Combined-with-lexicon-count quality threshold |
| `MIN_TTR` | `0.1` | Repetitive-text guard (Type-Token Ratio) |
| `ERROR_KEYWORDS` | `["Access Denied","403 Forbidden",...]` | Phrases that mark extraction as failed |

---

### Strategy chain

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `READ_TOTAL_BUDGET` | `90.0` | Wall-clock cap (seconds) across tiers 1-5. NoVNC exempt. |
| `EXTRACT_TIMEOUT` | `30.0` | Per-tier extraction timeout |
| `SEARCH_TIMEOUT` | `10.0` | SearXNG request timeout |
| `DEFAULT_TIMEOUT` | `30.0` | Generic HTTP timeout |
| `DYNAMIC_CONTENT_WAIT` | `2000` | Playwright post-load settle (milliseconds) |
| `SCROLL_ITERATIONS` | `5` | Scroll steps for infinite-scroll pages |
| `SCROLL_STEP_PX` | `1500` | Pixels per scroll step |
| `MAX_REQUESTS_PER_CRAWL` | `5` | Crawlee request cap |

---

### Extraction

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `READABILITY_FALLBACK_MIN_CHARS` | `200` | Absolute floor on the trafilatura result below which readability-lxml runs and the longer of the two is returned, applied after the recall pass below. See [ADR-007](architecture/decisions/ADR-007-structured-output-and-readability-fallback.md) |
| `CONTENT_RECALL_FALLBACK_RATIO` | `0.75` | Length of trafilatura's precision pass divided by the page's plain text length (BeautifulSoup `get_text` after noise tags are removed) below which a second pass runs with `favor_recall=True`. The longer of the two passes is returned. `0` never runs the second pass, `1` always runs it. See [ADR-009](architecture/decisions/ADR-009-recall-pass-for-thin-precision-extractions.md) |

The default is derived from measurements, because no published source gives a ratio of extracted text to page
text. Trafilatura's own documentation says to reach for `favor_recall` "when parts of your documents are missing"
and that results "vary on link lists, galleries, or catalogs" (its Python usage and troubleshooting pages), and its
benchmark page scores recall mode at precision 0.899 and recall 0.939 against 0.906 and 0.943 for the default on an
article corpus, so recall mode is not a free upgrade. Trafilatura's internal fallback rules compare two extractions
against each other, never against the whole page: readability replaces its own output only when at least twice as
long, jusText only when three times as long. Mozilla Readability's `charThreshold` is an absolute 500 characters.
On 2026-09-10 the precision pass covered 0.90 to 1.00 of the plain text on nine article pages (gnu.org,
peps.python.org, the docs.python.org tutorial, the kernel.org coding style guide, paulgraham.com, danluu.com, MDN,
keepachangelog.com, trafilatura's own documentation) and 0.19 to 0.87 on twelve same-day news articles (Guardian,
Ars Technica, TechCrunch, The Verge, BBC, Wired), where the recall pass returned the same text or, on one Ars
Technica article, 1924 characters against 8956. On the pages where the precision pass dropped real content it
covered 0.13 to 0.17 (three books.toscrape.com listings, where the recall pass restored every title) and 0.61
(quotes.toscrape.com page 2, where it restored 29 dropped lines). 0.75 is the midpoint between the highest measured
defective ratio, 0.61, and the lowest ratio at which the precision pass was already complete, 0.90. The second pass
cost 25 to 33 milliseconds on 50 to 390 kilobyte pages, and because the longer result wins it cannot lose content.

---

### Browser and CAPTCHA infrastructure

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `PLAYWRIGHT_HEADLESS` | `false` | Set `true` in CI or any container without an X server |
| `FLARESOLVERR_URL` | `http://localhost:8191/v1` | FlareSolverr Cloudflare-bypass endpoint |
| `SELENIUM_BROWSER_CDP_URL` | `ws://localhost:4444/playwright` | CDP URL for remote browser (legacy naming) |
| `SELENIUM_BROWSER_VNC_URL` | `http://localhost:7900` | Local NoVNC fallback |
| `PUBLIC_VNC_URL` | `http://localhost:7900` | Public NoVNC URL; `http://ngrok:4040/api/tunnels` for dynamic Ngrok |
| `NOVNC_TIMEOUT_SECONDS` | `600` | NoVNC monitor task lifetime (cookie capture window) |

---

### Container-only variables

These are read by the image itself, not by `config.py`, so they have no entry in
[src/config/config.py](../src/config/config.py) and only apply when the service runs in a container.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `VNC_PASSWORD` | unset | Password for the NoVNC desktop. `docker-entrypoint.sh` turns it into an encrypted x11vnc password file at boot. Unset means x11vnc runs with `-nopw` and the container logs a warning. The VNC protocol truncates the value to 8 characters. |

Two further variables belong to sibling containers in the scrapper compose stack rather than to this service, and both
are mandatory there. `SEARXNG_SECRET` is SearXNG's session-signing key, which is why the settings overlay carries no
`secret_key` entry, and `NGROK_AUTHTOKEN` authenticates the NoVNC tunnel.

---

### Persistence

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for clearance-cookie persistence |
| `USER_AGENTS_PATH` | `src/assets/user_agents.json` | Rotated UA pool for cheap tiers |
| `FILE_ENCODING` | `utf-8` | Default file encoding |

---

### Choosing values

- **`READ_TOTAL_BUDGET`**: 90 s is the default; tune up if your typical Playwright sites take more than 30 s
  per render, tune down if a chat assistant is the caller and 30 s already feels broken.
- **`PLAYWRIGHT_HEADLESS`**: `false` is the stealth-friendly posture and matches the Docker base image which
  ships Xvfb. Flip to `true` only when there is no display server (lightweight CI, bare-metal headless host).
- **`PUBLIC_VNC_URL` vs `SELENIUM_BROWSER_VNC_URL`**: the public URL is what gets returned in the 428 body
  for the human; the local URL is the in-cluster fallback when Ngrok cannot be reached. The dynamic Ngrok
  path uses `http://ngrok:4040/api/tunnels` to discover the active public URL at runtime.
- **`READ_TOTAL_BUDGET` and `STRATEGY_DURATION_SECONDS` histogram buckets**: the metrics histogram buckets at
  `[0.1, 0.5, 1, 2, 5, 10, 30, 60, 90, 120, 300, 600]` cover up to NoVNC's full timeout. If you raise the
  budget past 90 s, also widen the histogram buckets so the upper tail is observable.
