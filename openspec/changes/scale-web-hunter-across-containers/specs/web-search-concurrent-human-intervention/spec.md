## ADDED Requirements

### Requirement: A NoVNC window is reached through the edge proxy by the host name of its copy

The edge proxy SHALL route a request whose path starts with `/novnc/<name>/` to port 7900 of the container `<name>` with
that prefix removed, WebSocket upgrades included, only when `<name>` is `ascend-web-hunter` or 12 lower case hexadecimal
characters. It SHALL answer 404 for any other path under `/novnc/` without contacting an upstream. The VNC password of
each display SHALL stay the check a human passes, and the proxy SHALL add no login of its own. `NOVNC_PUBLIC_URL` SHALL be
the address of this proxy, or of a gateway that forwards `/novnc/` to it.

#### Scenario: The window of the copy that owns the flow

- **WHEN** two copies run with `NOVNC_PUBLIC_URL` set to the proxy, and a flow is open on the copy with host name `<a>`
- **THEN** `<NOVNC_PUBLIC_URL>/novnc/<a>/vnc.html` answers 200 with the noVNC page of that copy
- **AND** a WebSocket upgrade to `<NOVNC_PUBLIC_URL>/novnc/<a>/websockify` is answered 101

#### Scenario: A name that is not a copy

- **WHEN** a caller asks for `/novnc/ascend-agent/vnc.html` or `/novnc/../vnc.html`
- **THEN** the proxy answers 404

### Requirement: The public tunnel reaches only NoVNC

The Ngrok tunnel SHALL point at a listener of the edge proxy that carries only NoVNC routes and no route to the API or
the metrics. With one copy and `NOVNC_PUBLIC_URL` unset, the tunnel's root path SHALL reach the NoVNC server of that copy,
so today's `PUBLIC_VNC_URL` resolution keeps working.
When the optional setting `NGROK_DOMAIN` is set, the tunnel SHALL start on `https://<NGROK_DOMAIN>`. When it is empty,
the tunnel SHALL start on an address Ngrok assigns, as before this change.

#### Scenario: One copy, no public base address

- **WHEN** one copy runs with `NOVNC_PUBLIC_URL` unset and a read needs a human
- **THEN** the 428 answer carries the tunnel address resolved through `PUBLIC_VNC_URL`, as before this change
- **AND** that address opens the display of the one copy

#### Scenario: The API is not on the tunnel

- **WHEN** a caller requests `/api/v1/web/search` or `/metrics` through the tunnel's listener
- **THEN** the request does not reach the API or the metrics of any copy

#### Scenario: A fixed tunnel domain

- **WHEN** `NGROK_DOMAIN` is set to a domain the ngrok account holds and `NOVNC_PUBLIC_URL` is `https://<NGROK_DOMAIN>`
- **THEN** the tunnel serves `https://<NGROK_DOMAIN>` after every restart of the Ngrok container
- **AND** a 428 answer of any copy carries a `vnc_url` starting `https://<NGROK_DOMAIN>/novnc/<host name of that copy>/vnc.html`
