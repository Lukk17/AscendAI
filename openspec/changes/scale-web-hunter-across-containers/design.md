## Context

Build group 2, position 11 of the owner build order of 2026-10-04, the last change of the group (owner answer 96 of
2026-10-08). The owner deploys ascend-web-hunter on its own through `apps/ascend-web-hunter/deploy-standalone/` right
after group 2 and runs it as several containers, so nothing it needs may wait for group 3.

What is true when this change starts, read on 2026-10-08 and to be read again in task 1.1, because the ten changes
before it edit the same files:

- `compose.ascend-web-hunter.yaml` (lines 169 to 239) and `deploy-standalone/compose.yaml` (lines 154 to 218) fix
  `container_name: ascend-web-hunter`, `hostname: ascend-web-hunter` and `ports: "7021:7021"` on the service, and carry
  the network alias `ascend-web-hunter`. Docker refuses a second container with the same name, and a fixed host name
  would give every copy the same name.
- `ngrok-ascend-web-hunter` runs `http ascend-web-hunter:7900`, a direct tunnel to the NoVNC server of the one
  container. With several copies that name answers with a different copy each time.
- `open-several-novnc-windows-at-once` Decision 11 (owner answers 94.4 and 95.1) builds every `vnc_url` as
  `<NOVNC_PUBLIC_URL>/novnc/<hostname>/vnc.html?autoconnect=true&path=novnc/<hostname>/websockify` and leaves the router
  to the platform gateway of `harden-cloud-deployment` (build group 3, task 2.7), and leaves open which change removes
  the three fixed lines. The image's NoVNC server listens on 7900 (`supervisord.conf` line 21) and noVNC 1.3.0 opens its
  WebSocket at `/<path>` from the root of the host.
- `infra/observability/prometheus/prometheus.yaml` line 51 scrapes the one static target `ascend-web-hunter:7021`. With
  several copies each scrape reaches one copy chosen by DNS, so the series mix copies.
- The rate limiter of `ascend-python-common` keys a caller by `get_remote_address` (`rate_limit.py` line 14). Behind a
  proxy every host caller would have the proxy's address.
- The agent reaches the service at `http://ascend-web-hunter:7021` (`application-docker.yaml` line 54). The compose
  service name resolves to every copy on the stack network.
- These places address the container by the fixed name (grep of 2026-10-08, outside `openspec/`, source and tests):
  `.github/workflows/e2e.yaml` lines 217, 272, 273 and 302, `apps/ascend-agent/e2e/README.md` lines 203, 205 and 245,
  `apps/ascend-web-hunter/README.md` line 48, `docs/running.md` lines 96 and 108, `docs/troubleshooting.md` lines 77
  and 83, `e2e/README.md` lines 166 and 170, `e2e/testing/README.md` line 94, spec 7 lines 208 and 212, spec 10 line 100
  and its template line 14, root `AGENTS.md` line 180, `apps/ascend-web-hunter/AGENTS.md` lines 163 to 166,
  `docs/E2E_RUN_SCENARIOS.md` lines 40 to 48, `docs/DEPLOYMENT.md` line 16 and the IDE run configuration
  `apps/ascend-web-hunter/.run/ascend-web-hunter Run.run.xml` (its own `docker run` with `containerName`
  `ascend-web-hunter` and host port 7021). The Bruno environment `ascend-local.yml` holds no host name of the service:
  every web-hunter request goes to `{{protocol}}://{{baseUrl}}:7021`, which the edge proxy answers.
- Earlier group 2 changes add more such lines before this one runs (for example the `docker exec ascend-web-hunter
  printenv` checks of `add-ascend-python-common` tasks 9.10 and 9.11), so task 6.1 greps again at implementation time.

## Goals / Non-Goals

Goals:

- Any number of ascend-web-hunter copies from one setting, in both compose files, default 1.
- One entry point on port 7021 that spreads requests over the copies and routes a human to the NoVNC window of the copy
  that owns it.
- Today's single container behaviour, the Ngrok tunnel included, keeps working with the setting unset.
- Every multi container mechanism of group 2 proven together by one live check with two copies.
- No document, spec, run configuration or script left that addresses the service by a container name.

Non-Goals:

- No change to the flow records, the crawl claims, the purge channel, the retention lock, the rate limit storage or the
  stateless MCP mode. They belong to the earlier changes and this change only proves them together.
- No platform gateway. `harden-cloud-deployment` keeps its own gateway for the agent and Keycloak, and reuses this
  proxy for NoVNC (D9).
- No scaling of SearXNG, Redis or Ngrok. They keep their fixed names.
- No autoscaling. The owner sets the number of copies. A scaled company deployment of several copies with an
  autoscaler: company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it.
- No host port per copy and no host port range (owner answer 98.6 of 2026-10-08). The edge proxy is the one published
  port.

## Decisions

### D1: One setting for the number of copies

`deploy.replicas: ${WEB_HUNTER_REPLICAS:-1}` on the `ascend-web-hunter` service of both compose files, next to its
existing `deploy.resources`. The name follows `OPENCLAW_HOST_APPS_REPLICAS` of `add-openclaw-plugin-host` (service name
without the `ascend-` prefix, then `_REPLICAS`) and `WEB_HUNTER_ALLOWED_PRIVATE_HOSTS` of `add-ascend-python-common`. The
count lives in `.env`, so every command still runs against the main compose file with no `-f` and no `--scale` flag.

The service loses `container_name`, `hostname` and its `ports` entry. It keeps its network alias `ascend-web-hunter`,
which applies to every copy. Docker names the copies `<project>-ascend-web-hunter-<n>` and gives each its short container
ID (12 lower case hexadecimal characters) as host name, which the stack network resolves (checked on 2026-10-08 in
`open-several-novnc-windows-at-once` Decision 11). With one copy the host name is that ID too.

Every other service keeps its fixed name: `searxng`, `ngrok-ascend-web-hunter`, the profile gated Redis
(`ascend-scrapper-redis` in development, `redis` in the bundle) and any service an earlier group 2 change added. None of
them must scale.

### D2: The edge proxy

A new compose service `ascend-web-hunter-edge` in both compose files: the official Caddy image, Alpine variant, pinned by
version and digest read at implementation time with `docker buildx imagetools inspect` (never guessed), the
configuration mounted read only from `infra/web-hunter-edge/Caddyfile` (development) and `edge/Caddyfile` next to the
bundle's `compose.yaml`, with no fixed `container_name` (nothing addresses it by container name, and a fixed name would
add one more collision between the two projects), `restart: unless-stopped`, `logging: *default-logging`,
`depends_on: ascend-web-hunter: condition: service_healthy`, `read_only: true` with a tmpfs for Caddy's data and
configuration folders, `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, and a healthcheck
`wget -q -O /dev/null http://127.0.0.1:7021/health` (the image ships BusyBox `wget`, checked in task 2.1), healthy when at
least one copy answers. Resource limits start at the Ngrok container's shape, 0.25 CPU and 128M with 0.05 CPU and 32M
reserved, and task 2.6 measures the real peak and adjusts them.

The Caddyfile, the same bytes in both places:

- Global options: `admin off` and `auto_https off`. The proxy speaks plain HTTP inside the stack. TLS in a deployment is
  the platform gateway's job (D9) or the operator's own reverse proxy (bundle README).
- Listener `:7021`, published as `127.0.0.1:${WEB_HUNTER_HOST_PORT:-7021}:7021` in development and
  `${WEB_HUNTER_HOST_PORT:-7021}:7021` in the bundle (owner answer 100.6 of 2026-10-09, the bundle README requires the
  host port, 7021 by default, and nothing else):
  - a request whose path matches `^/novnc/(ascend-web-hunter|[0-9a-f]{12})/` has the prefix `/novnc/<name>` removed and
    goes to `<name>:7900`, WebSocket upgrades passed through (Caddy's `reverse_proxy` passes them by default). An
    upstream address with a placeholder needs the port written after it, which `<name>:7900` does (Caddy
    `reverse_proxy` documentation, "Upstream addresses", Context7 `/caddyserver/website`, checked 2026-10-08).
  - any other path under `/novnc/` answers 404 with no upstream contacted.
  - every other request goes to the dynamic upstreams `dynamic a ascend-web-hunter 7021` with
    `refresh {$WEB_HUNTER_EDGE_DNS_REFRESH_SECONDS:5}s`, `lb_policy round_robin` and
    `lb_try_duration {$WEB_HUNTER_EDGE_TRY_DURATION_SECONDS:5}s` (both settings of D13, default 5 seconds), so a new
    copy gets traffic within that many seconds of its DNS entry and a request that cannot connect to a stopping copy is
    tried on the next one. The A record module is in the standard Caddy build (same documentation, "Dynamic upstreams",
    checked 2026-10-08).
- Listener `:7900`, never published: the same `/novnc/<name>/` route and the same 404, and every other path goes to
  `dynamic a ascend-web-hunter 7900` with the same two settings. This listener is the Ngrok target (D5). It carries no route to port 7021, so
  nothing that reaches it reaches the API.

The prefix is removed with `uri strip_prefix` or `uri path_regexp`, whichever the pinned version accepts with the
captured name, and task 2.2 proves it with requests, not by reading.

Rejected: Traefik (needs the Docker socket or labels on the copies to find them), nginx (its open source build resolves
an upstream name once at start and needs a resolver block and a variable to follow the copies), and no proxy at all with
DNS round robin to the copies (a host caller has no DNS view of the stack network, and nothing would route NoVNC).

### D3: The proxy keeps the request as the caller sent it

Caddy keeps the incoming `Host` header and sets `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host`, replacing
any `X-Forwarded-For` a caller sent, because no trusted proxy is configured in front of it. So the `MCP_ALLOWED_HOST_HEADERS`
check of `add-python-runtime-upgrades` (D14 there) sees `localhost:7021` or `127.0.0.1:7021` exactly as without the proxy.

Each copy sets `FORWARDED_ALLOW_IPS=${FORWARDED_ALLOW_IPS:-*}` (a setting of D13), which uvicorn reads as the default of its trusted proxy list, so
`request.client.host` and therefore the rate limit key of `get_remote_address` is the caller in front of the proxy. `*`
is safe here because no copy publishes a port: only containers on the stack network reach a copy, the proxy rewrites the
header of every outside caller, and an in-stack caller such as the agent is trusted already. Task 1.3 confirms in the
installed uvicorn that the environment variable is read, and the e2e check of D10 proves the key.

### D4: In-stack callers keep the service name

The agent keeps `http://ascend-web-hunter:7021`. Docker's DNS answers that name with every copy, and stateless MCP lets
any copy answer any request, so the agent needs no change and no extra hop. The spread is per connection, not per
request, which is enough for tool calls of seconds. The edge proxy is the entry point of host callers, Bruno, the e2e
runner and the bundle's users. The same holds for the reverse path: a copy reaches SearXNG, Redis and the object store as
before.

### D5: Ngrok points at the proxy's NoVNC listener

Both files change the Ngrok command from `http ascend-web-hunter:7900` to `http ascend-web-hunter-edge:7900`, and its
`depends_on` from `ascend-web-hunter` to `ascend-web-hunter-edge`. The tunnel therefore never exposes the API or the
metrics, only NoVNC, as today.

- One copy and `NOVNC_PUBLIC_URL` unset (today's default): `PUBLIC_VNC_URL` resolves the tunnel address through the Ngrok
  API exactly as today, the `vnc_url` names the root `vnc.html`, and the `:7900` listener sends the root path to the one
  copy. Nothing the human sees changes.
- Several copies: the root path would reach a copy chosen by DNS, so several copies need `NOVNC_PUBLIC_URL`, as Decision
  11 of `open-several-novnc-windows-at-once` already says. On the host itself that is the proxy,
  `NOVNC_PUBLIC_URL=http://127.0.0.1:7021` in development and `http://<host>:7021` in the bundle, and the `/novnc/<name>/`
  route of either listener reaches the right copy. A public address for several copies needs a fixed tunnel address,
  because the random Ngrok address changes on every restart.
- Fixed tunnel domain (owner answer 97 of 2026-10-08): the optional setting `NGROK_DOMAIN` holds a domain the owner's
  ngrok account holds, host name only, no scheme. When it is set, the Ngrok command of both files starts the tunnel on
  that domain, and the owner sets `NOVNC_PUBLIC_URL=https://<that domain>`, so every `/novnc/<name>/` route of the `:7900`
  listener is reachable from the internet, still behind the VNC password (D6). When it is empty, the command carries no
  extra flag and Ngrok keeps today's random address, which works with one copy.
  - The flag is `--url`. The ngrok agent command line reference shows `ngrok http 8080 --url https://bar.ngrok.dev` as
    "choose your endpoint URL instead of it being assigned" (https://ngrok.com/docs/gateway/agent/cli), and the agent
    changelog entry of agent 3.15.0 (2024-08-29) reads "Added `--url` agent CLI flag for creation of HTTP(S), TLS, and
    TCP protocol endpoints" and "Deprecated `--domain`, `--scheme`, and `--remote-addr` agent CLI flags, which have been
    replaced by `--url`" (https://ngrok.com/docs/gateway/agent/changelog). Both read through Context7 `/websites/ngrok`
    on 2026-10-08. The deprecated `--domain` is not used. Tasks 2.2 and 2.3 check that the Ngrok image of each file runs
    agent 3.15.0 or newer.
  - The flag is passed only when the setting is set through the Compose alternative value form: the command becomes
    `http ascend-web-hunter-edge:7900 ${NGROK_DOMAIN:+--url https://${NGROK_DOMAIN}}`. The Compose interpolation
    reference reads "`${VAR:+replacement}` -> `replacement` if `VAR` is set and non-empty, otherwise empty" and allows
    nested interpolation (https://docs.docker.com/reference/compose-file/interpolation/, read through Context7
    `/docker/docs` on 2026-10-08). Measured on 2026-10-08 with Docker Compose v5.1.0 and `docker compose config` on a
    scratch file outside the repository: with `NGROK_DOMAIN` empty the command is the two arguments `http` and
    `ascend-web-hunter-edge:7900`, and with `NGROK_DOMAIN=foo.ngrok-free.app` it gains the two arguments `--url` and
    `https://foo.ngrok-free.app`.
  - The sync rule applies: `NGROK_DOMAIN=` with a one line comment goes into the root `.env.example`, into
    `deploy-standalone/.env.example` and into the configuration table of the bundle README in the same task.

### D6: The VNC password stays

Every copy starts its own x11vnc with the `VNC_PASSWORD` of the stack, as today. The proxy adds no login of its own.
Required in the bundle, optional in development, unchanged. The bundle's NoVNC is now also reachable on port 7021 of the
host under `/novnc/`, still behind that password, which the bundle README states.

### D7: Prometheus discovers every copy

`prometheus.yaml` replaces the static target `ascend-web-hunter:7021` with `dns_sd_configs` of type `A` on the name
`ascend-web-hunter`, port 7021, keeping the job name, the metrics path and the `service` relabel to `ascend-web-hunter`.
Each copy becomes its own target with its own `instance` label. The dashboards that `sum by (service)` keep their
meaning. The OpenTelemetry resource of every copy keeps `service.name=ascend-web-hunter`, so traces of two copies share
one service name, which is accepted (Risks).

### D8: Commands name the compose service

A command that needs the inside of a copy uses the compose form: `docker compose exec ascend-web-hunter <command>`,
`docker compose cp <file> ascend-web-hunter:<path>`, `docker compose logs ascend-web-hunter` and
`docker inspect $(docker compose ps -q ascend-web-hunter)`. With one copy they act on it. With several, `exec` and `cp`
act on the first copy and take `--index <n>` for another, and `logs` and `ps` cover every copy. Every compose command
still runs against the main file with no `-f` flag (root `AGENTS.md`). The `ai-driven-e2e-runner` delta states it for
the e2e suites.

The IDE run configuration `ascend-web-hunter Run` starts its own container from the module's Dockerfile, outside
compose, with the container name `ascend-web-hunter` and host port 7021. It addresses no compose container, so it keeps
its name. Its host port now meets the edge proxy instead of the compose container, and `docs/running.md` says to stop the
proxy first (task 6.3).

### D9: harden-cloud-deployment reuses the proxy

The NoVNC site of `harden-cloud-deployment` task 2.7 (build group 3) no longer routes names itself. It forwards
`/novnc/*` unchanged to `ascend-web-hunter-edge:7900`, which applies the name rule of D2, answers 404 for every other
path, and keeps the gateway's TLS. `NOVNC_PUBLIC_URL` in a deployment is that site's address. Its task 1.2 moves the
`${EXPOSE_BIND:-127.0.0.1}:7021:7021` form to the edge proxy, because the `ascend-web-hunter` service no longer
publishes a port. Edited in its tasks 1.2, 2.7, 5.2 and 11.4 and its design D2 by this round.

### D10: One live check runs two copies

The automated spec `<N>-concurrent-interventions-test.md` of `open-several-novnc-windows-at-once` task 11.3 already runs
alone and owns the NoVNC slots, so it gets a Part B, updated in place, that runs two copies and touches every mechanism
once. It recreates the service once at its start with `WEB_HUNTER_REPLICAS=2`, `NOVNC_PUBLIC_URL=http://127.0.0.1:7021`
and the sweep's `WEB_HUNTER_ALLOWED_PRIVATE_HOSTS=e2e-fake-site` in the shell of one `docker compose up -d` command
(none is a secret, owner answer 85.1 covers keys only), and once at its end, always, with only the sweep's allow list
set. A request aimed at one copy runs inside it through `docker compose exec --index <n> ascend-web-hunter curl ...`
against `localhost:7021`, a request through the proxy goes to `127.0.0.1:7021`. Every assertion is an HTTP status, a
body, a header, a per copy `/metrics` value or a Redis key, never a log line. The steps are in task 5.1.

The retention lock step needs a short sweep interval. The spec sets `DOWNLOAD_RETENTION_SWEEP_SECONDS=10` in the same
one command, which needs the development compose line to read `${DOWNLOAD_RETENTION_SWEEP_SECONDS:-900}`. Task 1.1 checks
the line `add-file-download` task 8.5 wrote and task 2.4 adds that form if it is not there. The step needs the module
`web-download`, so it runs only when `COMPOSE_PROFILES` holds it and is reported as not run otherwise, never as passed.

### D11: The bundle runs the same shape

The bundle gets the same `ascend-web-hunter-edge` service, the same Caddyfile bytes (`edge/Caddyfile`, a copy of
`infra/web-hunter-edge/Caddyfile` kept byte identical like `searxng/settings.yml`, so `diff` is the whole check), the same
`WEB_HUNTER_REPLICAS` and the same Ngrok target. The intended differences are only the published address of 7021
(all interfaces in the bundle, `127.0.0.1` in development) and the ones the list already holds. Its image tag moves to
`lukk17/ascend-ai-ascend-web-hunter:v0.0.17`, the version of this change. That tag exists only after the owner runs the
release workflow, which this change never runs (owner rules on automation runs). The bundle's Redis is already bundled
and always on, which every shared mechanism needs.

### D12: Version

ascend-web-hunter `0.0.17`, from the `0.0.16` of `add-file-download` (owner decision of 2026-10-08, one named version
per change, in build order). The files every bump of group 2 touches: `version` in `pyproject.toml`, the `Version`
line of `apps/ascend-web-hunter/AGENTS.md`, `docs/architecture/arc42/02-constraints.md` and one `## [0.0.17]` entry at
the top of `CHANGELOG.md`. In the same commit, `service.version` inside `OTEL_RESOURCE_ATTRIBUTES` of the development
compose file moves to `0.0.17` (the line `add-ascend-python-common` task 8.4 moved to `0.0.7`, finding F5 of
`fix-linux-docker-host-access`), and the bundle's image tag moves to `v0.0.17` (D11).

### D13: Every value with a default is a setting (owner rule 98 of 2026-10-08)

| Setting | Read by | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `WEB_HUNTER_REPLICAS` | compose (`deploy.replicas`) | `1` | Number of ascend-web-hunter copies (D1) |
| `FORWARDED_ALLOW_IPS` | uvicorn in each copy | `*` in both compose files | Addresses whose `X-Forwarded-For` a copy trusts (D3) |
| `WEB_HUNTER_EDGE_DNS_REFRESH_SECONDS` | Caddy in `ascend-web-hunter-edge` | `5` | How often the proxy looks up the copies under the service name (D2) |
| `WEB_HUNTER_EDGE_TRY_DURATION_SECONDS` | Caddy in `ascend-web-hunter-edge` | `5` | How long the proxy tries other copies for one request (D2) |
| `NGROK_DOMAIN` | the Ngrok command | none, optional | Fixed tunnel domain (D5, owner answer 97) |

Both compose files pass each setting with a default as `- VAR=${VAR:-default}` on the service that reads it, and
`WEB_HUNTER_REPLICAS` as `replicas: ${WEB_HUNTER_REPLICAS:-1}`. The Caddyfile reads the two edge settings as
`{$VAR:5}`, Caddy's environment placeholder with a default, so the file's own default equals the compose default. The
sync rule of `apps/ascend-web-hunter/AGENTS.md` applies to each: a commented `# VAR=default` line with a one line comment
in the root `.env.example` and in `deploy-standalone/.env.example` (`NGROK_DOMAIN=` stays an empty line, it has no
default), and a row in the configuration table of the bundle README. Each gets a row in
`apps/ascend-web-hunter/docs/configuration.md` whose description ends with "Added by
`scale-web-hunter-across-containers`.", in the same commit as the setting. The edge proxy and Ngrok rows go into its
"Container-only variables" section, where the variables of the sibling containers of the scrapper stack already live
(`NGROK_AUTHTOKEN`, `SEARXNG_SECRET`), so the scrapper stack keeps one reference.

`FORWARDED_ALLOW_IPS` has two defaults on purpose. uvicorn's own default, `127.0.0.1`, stays for a native run, where
the copy publishes its port and no proxy writes the header, so `*` would let any caller choose its address. The compose
default `*` holds only behind the edge proxy (D3). This is the same split `OBJECT_STORE_S3_ENDPOINT` and `REDIS_URL` have
(native default in code, container default in compose, owner answer 94.3).

Values that stay fixed, with the reason:

- The listener ports `:7021` and `:7900` of the proxy and the upstream ports 7021 and 7900 of the copies. They are the
  container contract that the agent, Ngrok, the gateway of `harden-cloud-deployment` and the healthchecks name, and 7900
  is fixed by the image's `supervisord.conf`.
- `lb_policy round_robin`, the name rule `^(ascend-web-hunter|[0-9a-f]{12})$`, the path prefix `/novnc/` and the
  service names: a policy name, a name format and API paths.
- The edge's resource limits, measured in task 2.6, and its healthcheck: compose resource limits and healthchecks stay
  fixed like those of every other service of the stack.
- The Caddy and Ngrok image versions: read at implementation time (tasks 1.2, 2.2 and 2.3).
- The counts and waits of the e2e Part B (ten requests, three sweep intervals and the like): test-only values.

## Risks / Trade-offs

- [Each copy carries its own Chromium pool, Xvfb, NoVNC and `shm_size`] → memory grows with the count. The development
  limit is 4G per copy and the bundle's 2560M per copy, so the bundle README's 8 GB arithmetic holds for one copy only,
  and the README says what each extra copy adds.
- [The agent's spread is per connection] → D4. A long lived connection pool may keep one copy busier. Accepted, the
  agent's calls are few and long.
- [Several copies with Ngrok and no fixed tunnel address] → the root NoVNC path reaches a copy chosen by DNS. With
  several copies the owner sets `NOVNC_PUBLIC_URL`, either to port 7021 of the host or, with `NGROK_DOMAIN` set, to
  `https://<NGROK_DOMAIN>` (D5), and the README says so next to both settings.
- [`NGROK_DOMAIN` set to a domain the ngrok account does not hold, or written with a scheme] → the tunnel is expected not to
  start (not measured, no such domain was tried). The `.env.example` comment and the README row say host name only and a
  domain of the owner's account.
- [`FORWARDED_ALLOW_IPS=*`] → any container on the stack network could claim another caller address. Only trusted
  services share that network, and no copy publishes a port.
- [A name that looks like a short container ID but is another container's] → the proxy forwards to port 7900 of that
  container, where nothing listens, and answers 502. No other port is reachable through the route.
- [Traces of two copies share one service name] → Prometheus tells copies apart by `instance`. A per copy trace
  attribute is not added, because Compose cannot give each copy a different environment value.
- [The bundle's image tag names a version not yet published] → the owner runs the release workflow before deploying,
  and the bundle README's upgrade section already describes the tag.

## Migration Plan

1. Land the compose, Caddyfile and Prometheus edits with `WEB_HUNTER_REPLICAS` unset, so the stack runs one copy behind
   the proxy. Bruno and the e2e suite keep their address `127.0.0.1:7021`.
2. Recreate the scrapper services with the owner's approval: `docker compose up -d` from the repository root creates the
   proxy and one copy without a fixed name, and removes the old container `ascend-web-hunter`.
3. Rollback is a code revert and the same `docker compose up -d`. No data moves, because every piece of state already
   lives in Redis and object storage.

## Open Questions

None. The fixed public Ngrok address for several copies is decided by owner answer 97 of 2026-10-08 (D5).

## Owner decisions of 2026-10-08

Answer 96: ascend-web-hunter is completely finished in build group 2, running as several containers at once included,
because the owner deploys it on its own through the standalone bundle right after group 2. This change is build group 2,
position 11, after `add-file-download`. It removes the fixed `container_name`, `hostname` and host port 7021 from the
service in both compose files, sets the count with `WEB_HUNTER_REPLICAS` (default 1), adds the Caddy edge proxy that
publishes 7021 and routes `/novnc/{hostname}/*` to port 7900 of that copy only for `ascend-web-hunter` or a 12 hex short
container ID, points `NOVNC_PUBLIC_URL` and Ngrok at it, keeps the VNC password and today's single container Ngrok
path, proves every multi container mechanism of group 2 with one two copy e2e check in an existing spec, makes
`harden-cloud-deployment` task 2.7 reuse the proxy, updates the standalone README and both `.env.example` files by the
sync rule, and names the version `0.0.17`.

Answer 97 (2026-10-08): an optional setting `NGROK_DOMAIN` is added. When it is set, the Ngrok container of
`compose.ascend-web-hunter.yaml` and of `deploy-standalone/compose.yaml` starts the tunnel on that fixed domain with the
agent flag `--url https://<NGROK_DOMAIN>`, passed only when the setting is set through the Compose form
`${NGROK_DOMAIN:+--url https://${NGROK_DOMAIN}}`, and the owner then sets `NOVNC_PUBLIC_URL=https://<that domain>`. When
it is empty, Ngrok keeps today's random address, which works with one copy. `NGROK_DOMAIN=` with a one line comment goes
into the root `.env.example`, into `deploy-standalone/.env.example` and into the bundle README configuration table in
the same task, by the sync rule. The open question about a fixed public Ngrok address is closed. Sources and the
measurement are in D5. Tasks 2.2, 2.3, 2.6, 3.1, 3.2, 3.3, 4.2, 7.1 and 7.2 carry it, and no task was added.

Answer 98: every value of this change that has a default is a setting (D13). Made external (name, default):
`WEB_HUNTER_REPLICAS` 1 (already a setting), `FORWARDED_ALLOW_IPS` `*` in both compose files (was the fixed
`FORWARDED_ALLOW_IPS=*`, uvicorn's own `127.0.0.1` stays for a native run), and the new
`WEB_HUNTER_EDGE_DNS_REFRESH_SECONDS` 5 and `WEB_HUNTER_EDGE_TRY_DURATION_SECONDS` 5 (were the fixed `refresh 5s` and
`lb_try_duration 5s` of the Caddyfile), read by Caddy as `{$VAR:5}`. `NGROK_DOMAIN` stays optional with no default.
Each is in both compose files, under the sync rule in both `.env.example` files and the bundle README, and gets a row in
`apps/ascend-web-hunter/docs/configuration.md` ending "Added by `scale-web-hunter-across-containers`." (new task 3.4).
Kept fixed, with the reason in D13: the host port 7021 (stack-wide form, only the bind address is a setting, listed for
the owner, and settled by owner answer 100.6 of 2026-10-09, see below), the container ports 7021 and 7900 (container contract, 7900 fixed by the image), the balancing policy, the
name rule, the paths and service names, the edge resource limits and healthcheck (like every other service), the image
versions (read at implementation time) and the test-only values of the e2e Part B. Tasks 2.1, 2.2, 2.3, 3.1, 3.2, 3.3,
4.2 and 7.1 carry it, and the requirement "One edge proxy is the entry point of every copy" names the two edge settings.
No test or measurement of this change uses LM Studio, and no text of it names the old `e2e` Spring profile, the overlay
mount or `SPRING_CONFIG_ADDITIONAL_LOCATION`.

Answer 98.6 and answer 99.1: no host port per copy and no host port range is planned (Non-Goals). Callers inside Docker
reach every copy by the compose service name `ascend-web-hunter` (D4), and host callers reach them through the one port
of the edge proxy. A scaled company deployment with an autoscaler: company plans it later in `plan-scaled-deployment`
(build group 5), this change does not wait for it.

## Owner decisions of 2026-10-09

Answer 100.6: every published host port is a setting `${<SERVICE>_HOST_PORT:-<today's port>}:<container port>`. `add-ascend-python-common` task 4.18 makes the host port of `ascend-web-hunter` the setting `WEB_HUNTER_HOST_PORT` (default 7021) in both web-hunter compose files. This change moves the published port to the edge proxy, so the setting moves with it: `127.0.0.1:${WEB_HUNTER_HOST_PORT:-7021}:7021` in development and `${WEB_HUNTER_HOST_PORT:-7021}:7021` in the bundle (D2, tasks 2.2 and 2.3), the `.env.example` comments and the bundle README row now name the edge proxy (tasks 3.1 to 3.3), and its row in `docs/configuration.md` changes its description (task 3.4). The spec requirement "One edge proxy is the entry point of every copy" names the setting. The container port 7021 and the listener ports stay fixed. The bullet of the D13 list that kept the host port fixed for the owner is removed. Bruno, the e2e suites and `NOVNC_PUBLIC_URL` keep port 7021, the default.
