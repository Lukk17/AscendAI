## MODIFIED Requirements

### Requirement: The edge gateway is the only publicly bound service

`compose.yaml` SHALL define a `gateway` service (Caddy 2, image pinned by version and digest) that is the only compose service publishing ports on all host interfaces: its container ports `80` and `443` on the host ports `GATEWAY_HTTP_HOST_PORT` (default `80`) and `GATEWAY_HTTPS_HOST_PORT` (default `443`). The gateway SHALL terminate TLS, through ACME when `ASCEND_DOMAIN` is a real domain and through Caddy's internal CA when `ASCEND_DOMAIN` is `localhost` or unset. Its configuration SHALL live in `gateway/Caddyfile` and SHALL proxy to `ascend-agent:9917`. The gateway SHALL carry no compose profile. The gateway SHALL NOT route to Grafana, the object store or the agent's management port `9918`, and SHALL NOT route any path of the agent's site to another service. Keycloak is a separate service on its own host address and port and SHALL appear in `gateway/Caddyfile` only as a separate site address with its own host name, which carries the per-client-address rate limits on the Keycloak login and token endpoints. The gateway SHALL NOT route any path of the agent's site to Keycloak. It SHALL also route `/hooks/<platform>/*` to port 18789 of the `channels` container that runs that platform (`ascend-openclaw-host-channels` by default), rewritten to the platform's webhook path, for Telegram and Slack and for every webhook platform the owner enables later by the same pattern. It SHALL answer 404 for `/api/v1/channel-host/*` without forwarding it. Nothing else SHALL reach a `channels` container, and nothing SHALL reach an `apps` container.

#### Scenario: External port scan shows only 80 and 443

- **WHEN** the stack runs on a cloud VM and an external host scans the VM's public IP
- **THEN** only ports 80 and 443 accept connections
- **AND** connections from outside the VM to 9917, 7020, 7017, 7021, 7022, 9998, 5001, 9080, 9020, 8191, 7077, 7078 and 18789 fail

#### Scenario: The agent is reachable through the gateway over TLS

- **WHEN** a client sends a prompt request to `https://<ASCEND_DOMAIN>/api/v1/ai/prompt`
- **THEN** the gateway terminates TLS, proxies to `ascend-agent:9917`, and the agent answers

#### Scenario: Actuator is not reachable through the gateway

- **WHEN** a client sends `GET https://<ASCEND_DOMAIN>/actuator/health` or `GET https://<ASCEND_DOMAIN>/actuator/prometheus`
- **THEN** the response is HTTP 404, because the agent serves actuator only on its internal management port `9918`

#### Scenario: Local TLS works without a domain

- **WHEN** a developer runs `docker compose up -d` with `ASCEND_DOMAIN` unset
- **THEN** the gateway serves `https://localhost` with a certificate from Caddy's internal CA
- **AND** no ACME request leaves the machine

#### Scenario: Keycloak has its own site

- **WHEN** a reviewer reads `gateway/Caddyfile`
- **THEN** Keycloak is reached only through a site block with its own host name that proxies to `keycloak:8080`
- **AND** no path of the agent's site proxies to Keycloak

#### Scenario: A channel webhook reaches its plugin through the gateway

- **WHEN** the `channels` module runs with Telegram in webhook mode and Telegram posts to `https://<ASCEND_DOMAIN>/hooks/telegram/...` with the webhook secret
- **THEN** the gateway forwards the request to port 18789 of `ascend-openclaw-host-channels` at the plugin's webhook path
- **AND** the same request without the secret is refused by the plugin

#### Scenario: The channel host prefix is not public

- **WHEN** a client sends `POST https://<ASCEND_DOMAIN>/api/v1/channel-host/messages`
- **THEN** the gateway answers 404
- **AND** the request does not reach the agent

### Requirement: Internal service ports bind to loopback by default

Every host-port publication in `compose.yaml` and `compose.ascend-web-hunter.yaml` except the gateway's SHALL use the form `"${EXPOSE_BIND:-127.0.0.1}:${<SERVICE>_HOST_PORT:-<host-port>}:<container-port>"`, where `<SERVICE>_HOST_PORT` is the host port setting of that service with today's port as its default (owner answer 100.6 of 2026-10-09). The services loki, vector, otel-collector, tempo, container-metrics-exporter, the bundled redis and `ascend-sandbox-runner` SHALL publish no host port. `compose.yaml` SHALL stay the single compose entry point. `ascend-openclaw-host-channels` SHALL publish `18789` only in that form, and a second `channels` service and every `apps` service SHALL publish no port.

#### Scenario: Fresh clone binds services to loopback

- **WHEN** a developer prepares `.env` from `.env.example` and runs `docker compose up -d --build`
- **THEN** `docker inspect` shows every published port except the gateway's bound to `127.0.0.1`
- **AND** `http://localhost:7020/health` and the other documented `localhost` addresses still respond

#### Scenario: Loopback binding blocks LAN access

- **WHEN** another machine on the same network requests `http://<host-LAN-IP>:7020/health`
- **THEN** the connection fails
- **AND** the same request from the host through `localhost` succeeds

#### Scenario: The channel host port binds to loopback

- **WHEN** the `channels` and `openclaw-apps` modules run
- **THEN** `docker compose config` shows `host_ip: 127.0.0.1` for port 18789 of `ascend-openclaw-host-channels`
- **AND** no `apps` service has a `ports` key
