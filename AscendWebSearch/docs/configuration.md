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
| `SEARXNG_USER_AGENT` | `AscendWebSearch/1.0` | Forwarded to SearXNG |
| `SEARXNG_X_REAL_IP` | `127.0.0.1` | `X-Real-IP` sent upstream |
| `SEARXNG_X_FORWARDED_FOR` | `127.0.0.1` | `X-Forwarded-For` sent upstream |

---

### Blocklist and content validation

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `BLOCKLIST_URL` | `https://secure.fanboy.co.nz/fanboy-annoyance.txt` | Ad blocklist fetched at startup; failure halts startup |
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
