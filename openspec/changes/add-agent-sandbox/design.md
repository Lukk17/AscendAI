## Context

See proposal.md for why. This section holds only the current state that shapes the approach.

- `add-agent-subagents` already decided that the library's default subagent tools (`ShellTools`, `FileSystemTools`) must never run inside the agent, and its `subagent-execution` spec says shell and file tools run only in the sandbox of this change. Runs carry `subagent_run_id`, `tenant_id` and `subagent_depth` in the tool context, and every run ends in `done`, `failed` or `cancelled` with a `SubagentRunChangedEvent` published after commit.
- Agent native tools reach the chat through `ChatToolset` and `AgentNativeTool`, owned by `add-agent-skills` (its D3), which also owns the tool context keys `request_id`, `tenant_id` and `embedding_provider` and the `TenantToolPolicy` port (its D16). The tenant comes from `TenantContext.currentTenantId()` of `add-keycloak-login`. The tool list of a run is computed at run start by `add-agent-subagents` D9. This change is build group 4, position 3 of the owner build order of 2026-10-04, after `add-agent-skills` and `add-agent-subagents` (positions 1 and 2) and after build group 3.
- `add-deployment-modules` owns module switching: the catalog, `ASCEND_MODULES` (from `COMPOSE_PROFILES`), `@ConditionalOnModule` and the always on part `core-chat`. By owner decision of 2026-10-03 the sandbox is core: always on and never switchable. It is no module of the catalog, the runner has no compose profile, no tenant module grant covers it, and there is no `app.sandbox.enabled` flag. Tenant policy can still switch the three tools off per tenant.
- `add-shared-scheduler` owns the db-scheduler engine and the system task contract (a recurring task bean with a name from one closed enum and a cron from `app.scheduler.system-tasks.<name>.*`). Work that writes shared state and must run once per deployment is a system task. Work that must run on every instance stays on that instance.
- `harden-cloud-deployment` sets `no-new-privileges` on every service, moves secrets to `.env`, binds published ports to `${EXPOSE_BIND:-127.0.0.1}`, removes `SYS_ADMIN` from ascend-web-hunter, and states that the Docker socket is never given to the agent.
- `compose.yaml` today mounts `/var/run/docker.sock` read-only into `container-metrics-exporter` and `otel-collector` (which replaced `vector` by owner answer 89.12 of 2026-10-08). A read-only bind of the socket file does not limit the Engine API at all, so those two services already hold full engine control. This change does not alter them, but it records the fact so nobody treats `:ro` as a protection for the runner.
- The agent runs on `eclipse-temurin:21-jre-alpine` and persists with Spring Data JDBC on PostgreSQL. It migrates with Liquibase today, and `upgrade-spring-boot-4` replaces Liquibase with Flyway 12.4.0 (its D15 to D17, owner decision of 2026-10-02): versioned SQL migrations `V<n>__<description>.sql` in `apps/ascend-agent/src/main/resources/db/migration/`. This change lands after that one, so its table is a Flyway migration (D12).
- Production target: one virtual server per customer, 32 GB, at Hetzner Cloud or Contabo. Development: Docker Desktop on Windows 11 with the WSL2 backend.

### Measured and sourced facts this design rests on

Checked on 2026-10-02:

| Fact | Source |
| :--- | :--- |
| Hetzner Cloud servers do not offer nested virtualization ("No, this is not possible on cloud server.") | https://docs.hetzner.com/cloud/servers/faq/ |
| Contabo VPS plans do not support nested virtualization. Only Contabo VDS and dedicated servers do | https://help.contabo.com/en/support/solutions/articles/103000271595-can-i-setup-nested-virtualization-on-my-server- |
| Firecracker needs read and write access to `/dev/kvm` | https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md |
| Kata Containers needs hardware virtualization (VT-x or AMD-V) and the KVM module | https://github.com/kata-containers/kata-containers and the OpenSandbox secure runtime guide |
| gVisor's default platform `systrap` uses seccomp traps and needs no hardware virtualization. It is "a better choice when running inside a VM, or on a machine without virtualization support" | https://gvisor.dev/docs/architecture_guide/platforms/ |
| gVisor needs Linux 5.6 or later on x86_64 or ARM64, installs into Docker with `runsc install`, and its single-binary auto-download ends in September 2026 (use the apt repository or tarball) | https://gvisor.dev/docs/user_guide/install/ |
| gVisor is Apache 2.0, released weekly (latest `release-20260928.0`, 2026-09-30) | GitHub API `google/gvisor` |
| Docker Desktop for Windows has no supported way to add `runsc`. The open feature request dates from 2026-05-09, the only workaround is an unofficial script that patches the Desktop VM and must be re-applied after Desktop updates | https://github.com/docker/desktop-feedback/issues/364, https://github.com/diogovalada/gvisor-docker-desktop-windows |
| Sysbox is Apache 2.0, "not officially supported by Docker", support on a best effort basis, last release v0.7.1 on 2024-07-31 | https://github.com/nestybox/sysbox and its releases page |
| E2B's runtime is Apache 2.0 and needs Linux with KVM for its Firecracker microVMs | https://github.com/e2b-dev/infra (now `e2b-dev/runtime`) |
| Daytona's public repository is AGPL-3.0 and "no longer maintained" since June 2026 | https://github.com/daytonaio/daytona |
| OpenHands is MIT. Its controller mounts the host Docker socket and runs each sandbox as an ordinary container | https://github.com/OpenHands/OpenHands, OpenHands runtime docs |
| Docker Sandboxes (`sbx`) run agents in microVMs, need KVM on Linux (Ubuntu 24.04+) or the Windows Hypervisor Platform, and ship under a proprietary licence after Docker sign-in | https://www.docker.com/blog/running-ai-agents-in-github-actions-with-docker-sandboxes/ and https://rywalker.com/research/docker-sandboxes |
| OpenSandbox is Apache 2.0, active (release 1.1.0 on 2026-09-21), has a Docker backend and a Java SDK. Its multi-tenancy needs Kubernetes ("Docker not supported"), its egress sidecar does not work with gVisor (gVisor has no iptables `nat` table, "Kata is the supported secure runtime"), and its Docker `network_mode` defaults to `host` | https://github.com/opensandbox-group/OpenSandbox, files `docs/guides/multi-tenancy.md`, `docs/guides/secure-container.md`, `docs/architecture/network/egress.md`, `server/configuration.md` |
| Stripe Smokescreen is MIT, active (v0.1.0 on 2026-09-21), allows egress by host name ACL and refuses private and internal addresses by default | https://github.com/stripe/smokescreen |
| docker-java is Apache 2.0, latest 3.7.1 (2026-03-18) | GitHub API `docker-java/docker-java` |

## Goals / Non-Goals

Goals:

- A boundary that holds on the owner's real production host, a virtual server without nested virtualization.
- Reuse maintained open source for the hard parts (the isolation runtime, the egress filter, the engine client) and write only the thin control service that ties them to tenants and runs.
- Nothing about a workspace is stored only in memory, so a crash of either process cannot leave a workspace forever.
- The runner API covers from the start what the later changes `add-coding-agent-delegation` and `add-self-built-integrations` need of it (D15 to D17), written here on 2026-10-02 from their required edits, so neither of them changes the runner.
- Only the workload runs under gVisor. Ascend's own services keep the engine's default runtime (owner decision 21.6 of 2026-10-02).

Non-Goals:

- Kubernetes. One Docker host per customer is the deployment model. A company Kubernetes deployment, with the runner as one copy per node, is planned later in `plan-scaled-deployment` (company, build group 5, position 9), and this change does not wait for it.
- Workspaces that outlive their owner (a run, or a conversation's idle and expiry rules of D11), snapshots, pause and resume.
- Running Ascend's own services, the runner, the egress proxies or any other compose service under gVisor (owner decision 21.6 of 2026-10-02). They are trusted code of this repository and run on the engine's default runtime.
- GPU access inside workspaces.
- Interactive terminals or long-lived inbound ports into a workspace.
- Credentials inside a workspace. A workspace never holds a credential of the platform. Authenticated calls go through the per-workspace credential gateway of D16, which holds the secret in its own memory-backed folder, never through an environment variable of the workspace.
- Rootless Docker on the production host as an extra layer under gVisor (owner decision of 2026-10-02). `runsc` support in rootless mode has limits that would need measuring first. The host runs rootful Docker with `runsc`.
- Disk-backed workspaces of any kind other than D15. The only disk-backed workspace is a profile marked `project-backed`, which mounts one project folder of the shared coding project area (owner decision 36.3 of 2026-10-02, which replaced the earlier plan of a fixed-size disk image per workspace). Every other profile keeps the tmpfs workspace of D4.
- Proving that no kernel bug exists. The escape suite proves the configuration. The user space kernel shrinks the kernel surface. Neither can promise more.

## Decisions

### D1: Isolation technology is gVisor (`runsc`) on plain Docker Engine

Comparison against the brief's candidates:

| Option | Licence | Docker Desktop on Windows (dev) | Hetzner or Contabo VPS (prod) | Maintenance | Boundary | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| gVisor `runsc` | Apache 2.0 | Not supported (issue 364), unofficial script only | Yes, `systrap` needs no virtualization | Weekly releases | User space kernel between workload and host kernel | Chosen |
| Kata Containers | Apache 2.0 | No (needs KVM in the Desktop VM) | No, needs KVM. Only on Hetzner dedicated or Contabo VDS and dedicated | Very active | Hardware VM per container | Rejected for the planned host |
| Firecracker based runners (E2B runtime, microsandbox, Kata FC) | Apache 2.0 | No | No, needs `/dev/kvm` | Active | microVM | Rejected for the planned host |
| Rootless Docker or Podman | Apache 2.0 | Docker Desktop is not rootless, Podman Desktop is a separate engine | Yes | Active | Shared host kernel, workload root maps to an unprivileged host user | Not used. Rootless Docker under gVisor is a non-goal for now (owner decision of 2026-10-02) |
| Sysbox | Apache 2.0 | No (Community Edition is Linux only) | Yes | Best effort, last release 2024-07-31 | Shared kernel with user namespaces, aimed at system containers | Rejected, stale and built for a different purpose |
| E2B self-hosted | Apache 2.0 | No | No, needs KVM and a Nomad cluster | Active | Firecracker | Rejected, KVM and heavy control plane |
| Daytona | AGPL-3.0 | Partly | Yes | Public repository unmaintained since June 2026 | Container | Rejected, unmaintained and copyleft for a SaaS |
| OpenHands runtime | MIT | Yes | Yes | Active | Plain container started through the host socket | Rejected as the isolation layer, it is an agent platform and gives no extra boundary |
| Docker Sandboxes (`sbx`) | Proprietary | Yes on Windows 11 with Windows Hypervisor Platform | No, needs KVM | Active | microVM | Rejected, closed source, sign-in, desktop tool, needs KVM on Linux |
| OpenSandbox server (Docker mode) | Apache 2.0 | Yes with `runc` | Yes with `runsc` | Active, young (created 2025-12), API not at a stable v1 | Whatever runtime it is given | Runner-up for the control service, see D2 |

Why gVisor: it is the only strong option that runs on the host the owner plans to rent. It intercepts every system call in a user space kernel written in Go, so a kernel exploit from the workload has to break gVisor first. It plugs into Docker as an OCI runtime (`--runtime=runsc`), so the runner uses the ordinary Engine API and the same code runs `runc` in development. The runtime is set per container, so only workspace containers get `runsc`. The engine's default runtime stays `runc`, and every Ascend service, the runner and the egress proxies run on it (owner decision 21.6 of 2026-10-02). `runsc install` registers the runtime without making it the default, and the deployment guide says never to set `default-runtime` to `runsc`.

Minuses, stated plainly:

- Not every system call is implemented. Some tools fail inside gVisor (for example anything that needs `systemd`, raw sockets, some `io_uring` use). The base image is tested under `runsc` before release.
- System call heavy work (large builds, many small files) runs slower than on `runc`. Acceptable for agent tasks, and measured in task 9.4.
- Development on Docker Desktop cannot use it in a supported way (D10).
- It does not give a hardware boundary. If the owner later rents a host with KVM (Hetzner dedicated, Contabo VDS), Kata is the stronger choice and only the runtime name in configuration changes, because the runner talks to the engine and not to the runtime.

### D2: Write a small runner, reuse the engine client and the egress filter, do not adopt OpenSandbox now

OpenSandbox was the closest ready-made fit and was checked in its source. It does not fit this deployment for four reasons, each from its own documentation:

1. Network off by default does not work with its design: its server reaches the `execd` daemon inside each sandbox over the network, so a sandbox without a network cannot be controlled.
2. Its per-sandbox allow list is an iptables sidecar that does not work with gVisor. With gVisor the only choice would be no filtering.
3. Its multi-tenancy needs Kubernetes and refuses to start in Docker mode.
4. Its server is a large Python service (Kubernetes, snapshots, ingress, Windows sandboxes, credential vault) whose API is not at a stable v1, and it would hold the Docker socket. A smaller service with the socket is a smaller target.

What is reused instead:

- The isolation runtime: gVisor (D1).
- The engine client: docker-java (`docker-java-core` with `docker-java-transport-httpclient5`), the client Testcontainers itself is built on.
- The egress filter: Stripe Smokescreen (D6).
- The command channel: the Engine API's own exec and attach, which work with `network_mode: none`, so no daemon is injected into the workspace.

What is written: one Spring Boot service with about a dozen classes (API controller, workspace service, container spec builder, path validator, command runner, file and archive operations, network and proxy manager, reaper, configuration, metrics). The agent talks to it only through its REST API, so the runner can be replaced later by OpenSandbox on Kubernetes with Kata without changing the agent, by writing a second adapter of the agent's `SandboxClient` port.

Language: Java 21 and Spring Boot 4.1, the same line as the agent after `upgrade-spring-boot-4`, so the repository keeps one Java toolchain, one set of conventions and Testcontainers based tests.

### D3: Runner API

Base path `/v1/workspaces`. Headers on every call except `/health`, `/ready` and `/actuator/prometheus`: `Authorization: Bearer <SANDBOX_RUNNER_TOKEN>` and `X-Ascend-Tenant: <slug>`. Optional `X-Run-Id` or `X-Conversation-Id` (UUID, at most one of the two) is stored as a label on create, so the runner never needs to know what a run or a conversation is. Errors are RFC 7807 problem details, built with Spring's `ProblemDetail` and sent as `application/problem+json`, with the same fields and rules as the agent's error body that `upgrade-spring-boot-4` defines (its D19, owner decision of 2026-10-02): `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`, for example `https://ascend.ai/errors/workspace-busy`), `title` (the HTTP reason phrase), `status`, `detail`, `instance` (the request path), a top-level `code` (the stable snake case code of the runner spec, for example `workspace_busy`) and the extension field `traceId` (the trace id of the current trace, owner decision 51.3 of 2026-10-03 in `upgrade-spring-boot-4` D19), and no `timestamp`. The runner is its own service, so it keeps its codes in its own enum and builds every body in one factory method, the same pattern as the agent's `ApiErrorCode`. A validation failure also carries `errors` with every validation message, the field D19 defines, with the same name and shape.

| Method and path | Body | Success | Notes |
| :--- | :--- | :--- | :--- |
| `POST /v1/workspaces` | `profile`, optional `cpus`, `memoryMiB`, `workspaceMiB`, `pids`, `ttlSeconds`, `network: {allow: [host names]}`, `project: {id}` (D15), `gateway: {routes: [...]}` (D16) | 201 workspace view | Unknown fields are refused (400), so an `image` field can never sneak in. 404 `project_not_found` and 409 `project_busy` (D15) |
| `GET /v1/workspaces/{id}` | | 200 view | |
| `GET /v1/workspaces` | | 200 list of views | Calling tenant only |
| `POST /v1/workspaces/{id}/commands` | `command`, optional `workdir`, `timeoutSeconds` | 200 command result | 409 `workspace_busy`, an expired workspace is 404 |
| `GET /v1/workspaces/{id}/files?path=` | | 200 `application/octet-stream` | 413 above the read limit |
| `PUT /v1/workspaces/{id}/files?path=&append=` | raw bytes | 204 | 413 above the write limit |
| `GET /v1/workspaces/{id}/archive?path=` | | 200 `application/x-tar` | 413 above the archive limit |
| `DELETE /v1/workspaces/{id}` | | 204 or 404 | |

The coding area endpoints under `/v1/coding-area` are listed in D15, and the image and service endpoints under `/v1/images` and `/v1/services` in D17. They use the same headers, token, tenant check and error body.

Workspace view: `id`, `tenantId`, `runId`, `conversationId`, `profile`, `state` (`ready` or `stopping`), `runtime`, `limits`, `network` (`none` or `allowlist` with the list), `storage` (`tmpfs` or `project`, D15), `gateway` (route names only, D16), `createdAt`, `expiresAt`. Command result: `exitCode`, `stdout`, `stderr`, `stdoutTruncated`, `stderrTruncated`, `timedOut`, `durationMs`.

Workspace ids are random UUIDs. The token is compared in constant time. The tenant check reads the `ascend.sandbox.tenant` label of the container on every call, so there is no second source of truth.

### D4: Workspace container settings

Built by one `ContainerSpecFactory` from configuration only, never from request fields other than the bounded limits:

- `HostConfig.runtime`: `app.runner.runtime` (`runsc` in production, D10).
- `User`: `10001:10001` for the container's main process, which is `sleep infinity` from the image. Commands and file operations run through exec as a second user `10002:10002` (D5).
- `CapDrop: ALL`, `SecurityOpt: no-new-privileges:true` (plus the engine's default seccomp profile, never `unconfined`), `Privileged: false`, `ReadonlyRootfs: true`.
- `Tmpfs`: `/workspace` with `size=<workspaceMiB>m,mode=0700,uid=10002,gid=10002` and `/tmp` with `size=<tmpMiB>m,mode=1777` (`app.runner.limits.tmp-mib`, default 64). No `Binds`, no `Devices`, no `VolumesFrom`, and no `Mounts` except the one project mount of a `project-backed` profile (D15), which replaces the `/workspace` tmpfs.
- `NanoCpus`, `Memory` and `MemorySwap` equal (no swap), `PidsLimit`, `Ulimits` for `nofile` and `nproc`.
- `NetworkMode: none`, or the workspace's own network (D6). `Dns: [127.0.0.1]` so the engine's embedded resolver has no working upstream. `ExtraHosts` empty. No `PortBindings`.
- `Env`: only `HOME=/workspace`, `LANG=C.UTF-8`, and with an allow list `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` pointing at the proxy's IP address (not a name, so no lookup is needed), with `gateway` added to `NO_PROXY` when the workspace has a credential gateway (D16). Nothing else, and nothing from the runner's own environment.
- `Hostname: sandbox`, `Labels` (D8), `AutoRemove: false` (the runner removes explicitly so it can log the reason), `RestartPolicy: no`.

Disk: Docker's `--storage-opt size` only works on overlay2 over XFS with project quotas, which neither Docker Desktop nor a default Hetzner image has. A size-limited tmpfs works everywhere and under gVisor. Its pages count against the workspace's memory limit, so the runner refuses to start when `workspaceMiB + tmpMiB` is not below `memoryMiB` for the defaults and refuses a create where that is false. Larger, disk-backed workspaces for coding runs are the `project-backed` profiles of D15, which mount one project folder of the shared coding project area on the host instead of the tmpfs (owner decision 36.3 of 2026-10-02). The tmpfs size check does not apply to them.

Defaults (all under `app.runner.limits`, each maximum under `app.runner.maxima` with the same key, every one a setting with its environment variable and compose line in D18). The owner confirmed the per-workspace defaults on 2026-10-02 and set the total to 4 workspaces at once, sized for one server with 24 to 32 GB of memory. At the defaults, 4 workspaces of 1024 MiB plus their 64 MiB proxies take at most 4352 MiB. A profile may set its own default limits inside the maxima below (D7). Integration services of D17 do not count against `max-workspaces`.

| Key | Default | Maximum |
| :--- | :--- | :--- |
| `cpus` | 1.0 | 2.0 |
| `memory-mib` | 1024 | 4096 |
| `workspace-mib` | 512 | 2048 |
| `pids` | 256 | 1024 |
| `ttl` | 30m | 2h |
| `command-timeout` | 120s | 900s |
| `output-bytes` | 65536 per stream | |
| `file-read-bytes` | 1 MiB | |
| `file-write-bytes` | 4 MiB | |
| `archive-bytes` | 50 MiB | |
| `max-workspaces-per-tenant` | 4 | |
| `max-workspaces` | 4 | |
| `tmp-mib` (the `/tmp` tmpfs of a workspace) | 64 | |
| `reaper-interval` (key `app.runner.reaper-interval`) | 60s | |

### D5: Commands, timeouts and file operations through exec

- The Engine API has no call to kill an exec'd process. Each command therefore runs as `timeout --kill-after=<k> --signal=TERM <n> bash -c '<command>'` (GNU coreutils in the image) as user 10002 with `WorkingDir` under `/workspace`, where `<k>` is `app.runner.commands.kill-after` in seconds (2, D18). GNU `timeout` signals its whole process group, which covers ordinary background jobs.
- A process can leave the group with `setsid`. So after a timeout the runner also execs `kill -KILL -1` as user 10002, which ends every process of that user and never the main process (user 10001). That is why commands and the main process use different users.
- The runner waits for the exec at most `timeout` plus `app.runner.commands.wait-margin` (5 seconds, D18). If the exec still has not ended, the runner destroys the whole workspace and answers with `timedOut: true` and the workspace gone. This is the last line of defence against a stuck engine call.
- Standard output and standard error are read through the attach stream into two bounded buffers. Reading stops at the limit and the rest is drained and dropped, so a command cannot fill the runner's memory.
- File read, file write and archive copy are execs too: `cat -- <path>`, `mkdir -p -- <dir> && cat > <path>` (or `>>`) with the body on standard input, and `tar -c -C /workspace -- <path>` streamed out with a byte counter. They run as user 10002 inside the workspace. The Engine API's own archive calls are not used, because they do not see tmpfs mounts and because running inside the workspace means a symbolic link can only ever resolve inside the workspace container.
- The path validator runs before any exec: relative, normalised, no `..`, no NUL, no leading `-`, at most 1024 bytes, then joined to `/workspace`. Paths are passed as separate arguments, never inside a shell string, except the command itself, which is the model's shell command by design.
- One `ReentrantLock` per workspace id, held in a bounded map, gives the one-operation-at-a-time rule (409 `workspace_busy` on `tryLock` failure). The map is only a lock table, not a record: losing it on restart loses nothing.

### D6: Network policy and the egress proxy

- Default: `network_mode: none`. The workspace has only a loopback interface.
- Allow list: on create the runner makes one network `ascend-sbx-<id>` with `internal: true`, starts one proxy container `ascend-sbx-<id>-egress` on that network and on `sandbox-egress`, then starts the workspace on `ascend-sbx-<id>` only. `internal: true` means the workspace has no route out except to the proxy. `sandbox-egress` is a bridge network declared in `compose.yaml` with `com.docker.network.bridge.enable_icc: "false"`, so proxies of different workspaces cannot reach each other.
- Proxy image: Stripe Smokescreen built from a pinned release tag in `infra/sandbox/egress-proxy/` (no official image exists), with a small entrypoint that turns the environment variable `ALLOWED_HOSTS` into Smokescreen's ACL file (default role, mode `enforce`, the listed domains) on its tmpfs and then starts Smokescreen. Smokescreen resolves each name and refuses private, loopback, link-local and other internal addresses by default, which also blocks `host.docker.internal`, `169.254.169.254` and every compose service.
- The proxy runs on `runc` (it is trusted code from this repository, not the workload) with the same hardening as other services: non-root, `CapDrop: ALL`, `no-new-privileges`, read-only root, `app.runner.egress.memory-mib` (64 MiB) memory, `app.runner.egress.cpus` (0.25) CPU, and the workspace's labels.
- Why one proxy per workspace and not one shared proxy: a shared proxy would have to tell workspaces apart by source address, which Smokescreen only supports with TLS client certificates or custom Go code. One small proxy per workspace keeps the allow list of one tenant away from every other tenant, and costs only when a run asked for network.
- Allow list rules: from configuration only (`app.sandbox.network.allow` globally and `app.sandbox.network.tenant-allow.<tenant>` in the agent), at most `app.sandbox.network.max-allow-entries` entries in the agent and `app.runner.egress.max-allow-entries` in the runner (32 each, D18), each a host name or `*.` plus a host name, never an IP literal or a bare `*`. The runner validates again.
- DNS from inside the workspace fails in both modes (D4 sets an upstream that does not answer). Clients that ignore `HTTPS_PROXY` simply fail, which is the safe failure.
- A workspace with a credential gateway (D16) has the gateway as a second neighbour on its internal network, and the gateway is the only route to the hosts it serves.
- An egress proxy is recreated, never reloaded, when its allow list changes, because Smokescreen ends on `SIGHUP` and cannot reload (asked for by `add-self-built-integrations` for its services, D17).
- Open mode (asked for by `add-mcp-tool-servers` for its compose service `mcp-egress-proxy`, which uses this image): the entrypoint also accepts `ALLOWED_HOSTS=*`, which writes an ACL with mode `open` and keeps the refusal of private, loopback, link-local and other internal addresses. The runner never starts a proxy in that mode, because its allow-list validator refuses a bare `*` (the rules above). Open mode exists only for a compose service that sets the variable itself.

### D7: Image profiles and updates

- `app.runner.profiles.<name>.image` holds an image reference with a digest, for example `ascend-sandbox-base@sha256:...`. Creates name a profile.
- The base profile is built from `infra/sandbox/images/base/Dockerfile`: a pinned `debian:<release>-slim` digest, packages `bash`, `coreutils`, `procps`, `tar`, `gzip`, `ca-certificates`, `git`, `python3`, `curl`, users 10001 and 10002, no `sudo`, no set-user-id binaries (removed with a `find / -perm -4000` step), `CMD ["sleep", "infinity"]`.
- A profile may set its own default limits inside the runner maxima (`app.runner.profiles.<name>.limits.*`), may be marked `project-backed: true` (D15), and has a `use`: `workspace` (the default, for `POST /v1/workspaces`) or `image` (only a base for `POST /v1/images` of D17, refused by a workspace create with `unknown_profile`).
- The runner of this change ships only the base profile. The profile `coding` (marked `project-backed`, defaults 2 CPUs and 4096 MiB) is added to the runner configuration by `add-coding-agent-delegation`, and the profiles `integration-runtime` (`use: image`) and `integration-verify` (`use: workspace`) from `infra/integrations/images/` by `add-self-built-integrations`, because their images are built in those changes. The runner supports their attributes from the start.
- The runner checks every profile image and the gateway image (D16) at startup with an image inspect and pulls only those that are missing, before reporting ready. A create never pulls.
- Updates: the image is rebuilt and scanned (Trivy, the existing supply chain gate of `docker-patterns`) on every change of its Dockerfile and at least monthly, and the new digest is written into the runner configuration in the same commit. No CI workflow is added by this change. The monthly rebuild is a documented manual step in the module README until the owner asks for automation.

### D8: Labels, reaper and crash cleanup

Labels on every object the runner creates (workspace container, proxy container, gateway container, area helper, integration container, integration image, network):

| Label | Value |
| :--- | :--- |
| `ascend.sandbox` | `true` |
| `ascend.sandbox.kind` | `workspace`, `egress`, `gateway`, `area-helper`, `service`, `image` or `network` |
| `ascend.sandbox.workspace` | workspace id |
| `ascend.sandbox.tenant` | tenant slug |
| `ascend.sandbox.run` | run id or empty |
| `ascend.sandbox.conversation` | conversation id or empty (a main chat workspace) |
| `ascend.sandbox.expires-at` | ISO-8601 instant in UTC |
| `ascend.sandbox.profile` | profile name |
| `ascend.sandbox.project` | project id of a `project-backed` workspace, or empty (D15) |
| `ascend.sandbox.integration` | integration id of a service or an image, or empty (D17) |
| `ascend.sandbox.spec-digest` | digest of a service's requested state (D17), only on service objects |

A service container has no `expires-at` label.

Create order is network, proxy, gateway, workspace (or integration container), with the labels on each, so a failure at any step leaves only labelled objects. Destroy order is the reverse.

The reaper runs once at startup before readiness turns ready and then every `reaper-interval`. It lists objects with `ascend.sandbox=true` and removes: anything whose `expires-at` has passed, any proxy, gateway or network whose workspace or service container is gone (`orphan`), any area helper older than its timeout (D15), any integration image whose integration has no service, that is older than one day and that the agent's reconcile list does not name (`orphan_image`, D17, the list as `add-self-built-integrations` D8 defines it), and anything whose labels do not parse. A service container has no expiry and is never removed by the reaper. Removal is force-remove for containers and remove for networks, each logged with the reason `expired`, `orphan` or `invalid_labels`. One runner runs per Docker host, and every agent copy on that host shares it (owner answer 98.9 of 2026-10-08). Each runner lists and removes only the objects of its own engine, so no lock between reapers is needed. A second runner on the same Docker host is not supported, and the module README says so.

Why the reaper is not a system task of `add-shared-scheduler`: that engine runs inside the agent on the agent's database, and the reaper must remove workspaces even while the agent is down or cannot reach the runner. The runner has no database and runs as one instance per Docker host, so its own Spring `TaskScheduler` is the right home. The agent side cleanup jobs of D11 and D12 do write shared state and are system tasks of the shared scheduler.

### D9: Runner security

- The runner mounts `/var/run/docker.sock`. That is equal to root on the host, so the runner is kept small and closed: no published port, only the stack's default network, a required bearer token of at least 32 characters from `.env` (`SANDBOX_RUNNER_TOKEN`, compose uses `${SANDBOX_RUNNER_TOKEN:?SANDBOX_RUNNER_TOKEN must be set}` on the runner and the agent, the same guard `SEARXNG_SECRET` uses, because the runner runs in every deployment, and the runner itself also refuses to start on a short token), non-root user with `group_add` of the socket's group id (`DOCKER_SOCKET_GID`, measured on each host by the deployment guide), `CapDrop: ALL`, `no-new-privileges`, read-only root with a tmpfs `/tmp`, memory 512 MiB.
- The runner never sets `Privileged`, `CapAdd`, `Binds`, `Devices`, `PidMode`, `IpcMode`, `UsernsMode` or `NetworkMode: host` on anything it creates, and sets `Mounts` only for the project mount and the area helper of D15. One unit test builds every container spec the runner can produce and fails on any of these.
- A socket filter proxy (for example Tecnativa docker-socket-proxy) was considered and rejected: it filters by API path, not by request body, so it cannot stop a compromised runner from creating a privileged container. The protection is that the runner is small, has no inbound route except the token, and has no internet access of its own.
- Secrets: the runner's own environment holds the token and, only from the optional file `integration-secrets.env` (owner answer 46.2 of 2026-10-02, asked for by `add-self-built-integrations` D11), the integration secrets. Compose loads that file with `env_file: [{ path: integration-secrets.env, required: false }]` on `ascend-sandbox-runner`, never the root `.env`, which holds every other secret of the stack. The file sits next to `compose.yaml`, is ignored by git and is documented by `integration-secrets.env.example`. Each variable is named `INTEGRATION_SECRET_<first 12 hex characters of the integration id, upper case>_<credential name, upper case>`, and the runner derives that name itself from a service's integration id and credential name. It never accepts a value or a variable name from a caller, and never returns, logs or labels a value.
- The agent sends the gateway secrets of a coding or publish workspace in the create body (D16). The runner writes every secret only into a gateway container's tmpfs through exec standard input, never into an environment variable, a label, a command or a log, and keeps no copy of a secret it was sent. Workspace containers get only the variables listed in D4.

### D10: Runtime per profile and development on Windows

- `app.runner.runtime` defaults to `runsc`. Under the Spring profile `production` the runner reads the engine's `/info` runtimes at startup and refuses to start when `runsc` is missing or when the configured runtime is anything else. It also refuses to start when the engine's `DefaultRuntime` is `runsc`, because every Ascend service must run on the default runtime and only workspaces on `runsc` (owner decision 21.6). The runner sets `HostConfig.runtime` explicitly on every container it creates: the configured runtime for workspaces and integration service containers, and `runc` for egress proxies, credential gateways, area helpers and every other sidecar.
- Docker Desktop on Windows: `.env` sets `SANDBOX_RUNTIME=runc` for local development. The runner logs one WARN banner at startup ("workspaces run on runc, which shares the host kernel, development only"), reports `runtime: runc` in `/ready` and tags its metrics with `runtime`. Every other setting of D4 to D6 is the same, so development still exercises capabilities, mounts, network, limits and paths.
- Owners who want gVisor locally have two choices, both documented, neither required: a WSL2 distribution with its own Docker Engine and `runsc` (run the runner there), or the unofficial Desktop script from issue 364. The `runsc` specific escape checks run on a Linux host in task 9.3.

### D11: Agent side

- Port `SandboxClient` (create, run, read, write, archive, destroy) in `service/sandbox/`, owned by this change and named the same way in `add-agent-subagents` D9a, adapter `HttpSandboxClient` on Spring's `RestClient` with a connect timeout of `app.sandbox.runner.connect-timeout` (2 seconds) and a read timeout of the command timeout plus `app.sandbox.runner.read-timeout-margin` (10 seconds), both settings of D18. A fake adapter backs the unit tests.
- Core, not a module (owner decision of 2026-10-03): no bean of `service/sandbox/`, the output controller or `SandboxProperties` carries `@ConditionalOnModule`. Every one of these classes is listed in the `core-chat` list of `ModuleMarkingCoverageTest` of `add-deployment-modules`, so they exist in every deployment, the output routes are always mapped, and the system tasks below are always registered. No module grant and no `module_denied` applies to the tools or the output routes. The `TenantToolPolicy` port of `add-agent-skills` is the only switch: a tenant whose policy does not allow a tool is not offered it. Its default denies only the tools listed in `app.tool-policy.denied-tools` of `add-agent-skills` (empty by default), so the owner can switch the three tools off for the personal deployment in configuration, and `add-tenant-policy` (company, build group 5) registers its allow-list implementation later.
- Owners of a workspace: a workspace belongs either to one subagent run or to one main chat conversation, never both. `SandboxWorkspaceService` keeps the mapping in the `sandbox_workspace` table (D12). For a run it also keeps the workspace id in the optional sandbox workspace id field of the run's `RunContext` (`add-agent-subagents` D8), which only this service reads and writes.
- Tools `shell`, `file_read` and `file_write` are the `AgentNativeTool` beans `ShellTool`, `FileReadTool` and `FileWriteTool`. They read `subagent_run_id`, `conversation_id` and `tenant_id` from the tool context. With a `subagent_run_id` the call uses the run's workspace. Without one (the main chat, owner decision 21.6 of 2026-10-02) it uses the conversation's workspace, and a main chat call with no `conversation_id` is refused with a tool error. `ChatToolset` applies the `TenantToolPolicy` port to them like every other agent native tool. Two runs, a run and its parent, and two conversations never share a workspace, and a subagent run started from a conversation never uses that conversation's workspace.
- Run workspace: created lazily on the first sandbox tool call of the run, with `ttlSeconds` equal to the run's remaining time limit plus `app.sandbox.run-ttl-margin` (60 seconds, D18), capped at the runner maximum, and with the tenant, run id, profile and allow list from `app.sandbox.*`. Lifecycle: a `@TransactionalEventListener(phase = AFTER_COMMIT)` on `SubagentRunChangedEvent` acts when a run becomes final: on `done` it copies `out` (see Results below), then it destroys the workspace and writes the reason (`RUN_FINISHED`, `RUN_FAILED`, `RUN_CANCELLED`, `AGENT_RESTARTED`). The restart sweep of `add-agent-subagents` D14 publishes the same event, so workspaces of runs closed at startup are destroyed too.
- Several agent instances (owner answer 87 of 2026-10-08, CANON 26.1): every workspace state lives in `sandbox_workspace` and in the runner, never only in one agent instance. A create first inserts its row in state `creating`. For a chat workspace the partial unique index on the open workspace of a conversation (D12) lets only one instance win when two turns of one conversation reach two instances at once, and the losing instance uses the winner's row once it reads `ready` (it reads the row again until the read timeout of `HttpSandboxClient` ends, and then answers a tool error naming the busy workspace). The room rule `chat.max-open-per-tenant` counts and closes inside one transaction that first takes the transaction-level Postgres advisory lock of the tenant, so two instances cannot both pass the count. A run workspace is used only by the run's own thread on its own instance, and its end is handled by the listener of `SubagentRunChangedEvent` on whichever instance publishes it, the restart sweep included.
- The runner of a workspace (owner answer 98.9 of 2026-10-08): one runner runs per Docker host and every agent copy on that host shares it. The create writes the base URL of the runner it calls, the creating instance's `app.sandbox.runner.base-url`, into `sandbox_workspace.runner_base_url` (D12). Every later call for that workspace (command, file read and write, archive, destroy) goes to the runner its row names, never to the calling instance's own configured runner, because the idle sweep, the room rule, the run lifecycle listener and the conversation delete may run on another agent copy than the one that created the workspace. `HttpSandboxClient` therefore takes the runner base URL per call and keeps one `RestClient` per base URL with the timeouts of this section. A runner that the row names and that does not answer is handled like every unreachable runner (`RUNNER_UNREACHABLE`, then `RUNNER_EXPIRED` by the idle sweep). How agent copies on several Docker hosts are deployed: company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it.
- Chat workspace: created lazily on the first sandbox tool call of a conversation, with `ttlSeconds` equal to `app.sandbox.chat.max-lifetime` (default 2 hours, the runner's maximum), the conversation id as label, and the same profile and allow list rules as a run. It is kept between turns, so files written in one turn are there in the next. The agent closes it, copying `out` first and then destroying it, when one of these holds:
  - no sandbox tool call for `app.sandbox.chat.idle-timeout` (default 30 minutes), reason `CHAT_IDLE`,
  - its runner expiry is less than two sweep intervals away, reason `CHAT_EXPIRING`,
  - the tenant already has `app.sandbox.chat.max-open-per-tenant` (default 2) open chat workspaces and a new conversation needs one, in which case the least recently used one of that tenant is closed first, reason `CHAT_ROOM_NEEDED`,
  - the conversation is deleted, reason `CONVERSATION_GONE`, with no copy, because the owner removed the conversation. The conversation delete closes it itself (see Conversation delete below), so no sweep looks for it.

  After a close, the next sandbox tool call of that conversation creates a fresh workspace, and its first tool result says that the earlier workspace was closed, why, and that its `out` folder was saved. A chat workspace that the runner expired before the agent closed it (agent down) is lost without a copy, and its record says `RUNNER_EXPIRED`.
- Idle sweep: the system task `sandbox-chat-idle-sweep` of `add-shared-scheduler` (cron `*/5 * * * *` in zone `UTC`, from `app.scheduler.system-tasks.sandbox-chat-idle-sweep.cron` and `.time-zone`) applies the first and second rule above. It is safe to run twice, because each close is a conditional state move from `ready` to `closing` and a second sweep skips rows that are not `ready`. The third rule runs inside the create call, and the fourth inside the conversation delete. It is the one agent side system task of this change (answer 93 of 2026-10-08, which folded the three agent side tasks into it and into the shared retention task of D12).
- Unreachable runner: a runner that does not answer a destroy leaves the record `ready` with `destroy_reason = RUNNER_UNREACHABLE`. The runner removes the container itself at its expiry (D8), so no retry task exists (answer 93 of 2026-10-08 removed `sandbox-destroy-retry`, which repeated the runner's own expiry). The idle sweep moves every record of a run or a chat workspace whose `expires_at` has passed and that is not yet `destroyed` to `destroyed` with `RUNNER_EXPIRED`, with a conditional update, so the record of an unreachable runner is closed at most one sweep interval after the runner removed the container, and the open chat workspace index never blocks a new workspace of that conversation.
- Conversation delete (owner answer 76.6 of 2026-10-08): this change extends the conversation delete of `add-chat-streaming-and-conversations` (its `ConversationService.delete`, D5) the way `add-agent-subagents` extends it for its runs. Before the Redis key is removed, it closes the conversation's open chat workspace with reason `CONVERSATION_GONE` and no copy. A runner that does not answer leaves the container to the runner's own expiry. Then, in the same Postgres transaction as the history rows, it deletes every `sandbox_workspace` row whose `conversation_id` is that conversation, chat and run workspaces alike, so the foreign key of D12 never blocks the delete. After the commit it deletes the output archives that the deleted rows named in `output_key`. An archive whose delete fails is logged at WARN with its key and does not fail the conversation delete. A run lifecycle event for a workspace whose record is already gone destroys the container and writes no record.
- Results: `GET /v1/workspaces/{id}/archive?path=out`, gzip on the agent side, upload with the agent's existing S3 client to bucket `app.sandbox.output.bucket` (default `sandbox-output`, never `knowledge-base`, because that bucket is indexed for RAG). A run workspace's archive is stored at `tenant/<tenantId>/sandbox-output/<runId>.tar.gz`, and a chat workspace's at `tenant/<tenantId>/sandbox-output/chat/<workspaceId>.tar.gz`, the same `tenant/<tenantId>/` prefix rule `add-tenant-isolation` sets for every object key and the same layout `add-file-download` uses for `tenant/<tenantId>/downloads/<sha256>/content`. The tenant id comes from the run's or the conversation's tenant, never from tool input. The key is stored on the workspace record. `SandboxOutputController` serves `GET /api/v1/runs/{id}/sandbox-output` after the same tenant and user check as the run endpoints, `GET /api/v1/conversations/{id}/sandbox-outputs` (the saved archives of that conversation, newest first, each with workspace id, close reason, size and time) and `GET /api/v1/conversations/{id}/sandbox-outputs/{workspaceId}` (one archive), both after the conversation's own tenant and user check.
- Sandbox time: by owner decision of 2026-10-02, sandbox time is its own metered operation type. The agent publishes one `UsageEvent` through `UsageEventPort.record` of `add-deployment-modules` whenever it records a workspace destroyed, with request type `sandbox`, the tenant and user, the conversation, the run id and parent run id of `add-agent-subagents` for a run workspace (null for a chat workspace), and `processing_ms` equal to the time from `created_at` to `destroyed_at` of the workspace record. A workspace whose create failed publishes none. The default `NoOpUsageEventPort` records nothing. `add-usage-metering-and-quotas` (company, build group 5) registers its ledger implementation later, which writes the `sandbox` ledger row from the event. The edit that change needs is listed under "Required edits to other changes".
- Configuration `app.sandbox`: `runner.base-url` (`http://ascend-sandbox-runner:9940` in the `docker` profile), `runner.token` (from `SANDBOX_RUNNER_TOKEN`), `runner.connect-timeout` (2s), `runner.read-timeout-margin` (10s), `run-ttl-margin` (60s), `profile` (`base`), `limits.*` (lower than or equal to the runner's maxima), `network.allow` (empty), `network.tenant-allow`, `network.max-allow-entries` (32), `output.bucket` (`sandbox-output`), `output.max-bytes`, `chat.idle-timeout` (30m), `chat.max-lifetime` (2h, at most the runner's `ttl` maximum), `chat.max-open-per-tenant` (2, at most the runner's `max-workspaces-per-tenant`), `chat.output-retention` (30d). There is no `enabled` key, because the sandbox is core and always on. `SandboxProperties` refuses to start on an empty `runner.token`. Every key with a default is a setting with an environment variable and a compose line, listed in D18 (owner rule 98 of 2026-10-08).

### D12: Table and its Flyway migration

Table `sandbox_workspace`:

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` primary key | The runner's workspace id |
| `tenant_id` | `VARCHAR(64)` not null | |
| `user_id` | `VARCHAR(255)` not null | |
| `owner_kind` | `VARCHAR(16)` not null | Check in `run`, `conversation` |
| `conversation_id` | `UUID` null | The same type as `subagent_run.conversation_id` and `conversations.id`, with the foreign key `fk_sandbox_workspace_conversation` to `conversations(id)` of `add-chat-streaming-and-conversations` and no delete action, the same rule as `fk_subagent_run_conversation` of `add-agent-subagents` D13, because conversation delete removes the conversation's rows itself in its transaction (owner answer 76.6 of 2026-10-08). Not null when `owner_kind` is `conversation` (check). For a run, the run's conversation when it has one |
| `run_id` | `UUID` null | Not null exactly when `owner_kind` is `run` (check). No foreign key, so this table does not depend on which tool created `subagent_run` |
| `profile` | `VARCHAR(64)` not null | |
| `network_mode` | `VARCHAR(16)` not null | Check in `none`, `allowlist` |
| `network_allow` | `TEXT` null | Comma joined host names |
| `limits` | `JSONB` not null | |
| `runtime` | `VARCHAR(16)` not null | As reported by the runner |
| `runner_base_url` | `VARCHAR(512)` not null | The base URL of the runner that created the workspace, the creating instance's `app.sandbox.runner.base-url`. Every later call for the workspace goes to this runner (D11, owner answer 98.9 of 2026-10-08) |
| `state` | `VARCHAR(16)` not null | Check in `creating`, `ready`, `closing`, `destroyed`, `failed` |
| `destroy_reason` | `VARCHAR(32)` null | Check in the closed set of D11: `RUN_FINISHED`, `RUN_FAILED`, `RUN_CANCELLED`, `AGENT_RESTARTED`, `CHAT_IDLE`, `CHAT_EXPIRING`, `CHAT_ROOM_NEEDED`, `CONVERSATION_GONE`, `RUNNER_EXPIRED`, `RUNNER_UNREACHABLE` |
| `commands` | `INTEGER` not null default 0 | |
| `created_at`, `expires_at`, `last_command_at`, `destroyed_at` | `TIMESTAMPTZ` | |
| `output_key` | `VARCHAR(512)` null | Object store key of the results archive |

Indexes: `(conversation_id)` for the conversation delete, partial unique `(run_id) WHERE owner_kind = 'run'`, partial unique `(tenant_id, conversation_id) WHERE owner_kind = 'conversation' AND state IN ('creating','ready','closing')` (one open chat workspace per conversation), `(tenant_id, created_at DESC)`, partial `(expires_at) WHERE state IN ('creating','ready')` for the retry and idle tasks, partial `(tenant_id, last_command_at) WHERE owner_kind = 'conversation' AND state = 'ready'` for the idle sweep and the least recently used choice. Explicit names for every constraint and index.

Retention: the shared retention task `record-retention` of `add-shared-scheduler` (its D15, owner answer 89.7 of 2026-10-08) deletes the records, and their archives, through two `RetentionEntry` beans this change registers in every deployment with no `@ConditionalOnModule`, because the sandbox is core: `sandbox-run-workspaces` (table `sandbox_workspace`, time column `destroyed_at`, age `app.subagents.limits.retention`, condition `owner_kind = 'run'` and the run no longer exists in `subagent_run` or finished more than that age ago) and `sandbox-chat-workspaces` (table `sandbox_workspace`, time column `destroyed_at`, age `app.sandbox.chat.output-retention`, condition `owner_kind = 'conversation'` and `state = 'destroyed'`). Each has a cleanup hook that deletes the results archive of `output_key` from the object store before the row goes, with the row's tenant bound, safe to run twice. The records of a deleted conversation are already gone, because the conversation delete removes them with their archives (owner answer 76.6 of 2026-10-08). The one agent side system task of this change, `sandbox-chat-idle-sweep`, joins the closed enum `SchedulerTaskName` of `add-shared-scheduler` and is registered in every deployment, because the sandbox is core (owner decision of 2026-10-03). `sandbox-destroy-retry` and `sandbox-workspace-retention` are gone (answers 89.7 and 93 of 2026-10-08).

Migration: the owner decided on 2026-10-02 that the agent moves from Liquibase to Flyway in `upgrade-spring-boot-4` (Flyway 12.4.0, its D15 to D17), which lands before this change. The table is created by one Flyway versioned SQL migration, `apps/ascend-agent/src/main/resources/db/migration/V<n>__create_sandbox_workspace.sql`, where `<n>` is the next free version at implementation time, after the migrations of the changes before this one. Flyway runs every migration in every deployment, also when the module is off (`add-deployment-modules` D15). Flyway runs forward only and the agent uses no paid Flyway feature, so there is no undo migration: an applied migration file is never edited, and removing the table later is a new versioned migration that drops it. Task 8.3 writes it.


### D13: Logs, metrics, traces

Runner metrics (Micrometer, names after `add-observability` D2 and D5, with the singular domain name `sandbox.` as the first segment, the same style as the agent's existing metrics such as `mcp.tool.duration` and as `skill.` of `add-agent-skills` and `subagent.` of `add-agent-subagents`):

| Metric | Type | Tags |
| :--- | :--- | :--- |
| `sandbox.workspaces.created` | counter | `outcome`, `network`, `runtime` |
| `sandbox.workspaces.destroyed` | counter | `reason` (`requested`, `expired`, `orphan`, `invalid_labels`, `timeout`, `error`) |
| `sandbox.workspaces.active` | gauge | `runtime` |
| `sandbox.commands` | counter | `outcome` (`ok`, `nonzero_exit`, `timeout`, `busy`, `error`) |
| `sandbox.command.duration` | timer | `outcome` |
| `sandbox.files` | counter | `operation`, `outcome` |
| `sandbox.limit.refusals` | counter | `limit` |
| `sandbox.reaper.removed` | counter | `kind`, `reason` |
| `sandbox.workspaces.seconds` | counter | `runtime` |
| `sandbox.gateways.created` | counter | `outcome` |
| `sandbox.gateways.removed` | counter | `reason` |
| `sandbox.area.helper.runs` | counter | `operation`, `outcome`, `area_mode` |
| `sandbox.area.free.bytes` | gauge | `area_mode` |
| `sandbox.images.built` | counter | `outcome` |
| `sandbox.images.refused` | counter | `reason` |
| `sandbox.services.active` | gauge | none |
| `sandbox.services.restarts` | counter | none |
| `sandbox.services.seconds` | counter | none |
| `sandbox.services.reserved.memory` | gauge | none |

`sandbox.workspaces.seconds` adds, when a workspace is destroyed for any reason, the seconds from its creation to its removal. It is the runner side measure of sandbox time (owner decision of 2026-10-02). The billing record of sandbox time is the usage ledger of `add-usage-metering-and-quotas`, written by the agent (D11).

Agent metrics: `sandbox.tool.calls` (`tool`, `outcome`, `owner` `run` or `conversation`), `sandbox.agent.workspaces` (`event` opened or closed, `reason`, `owner`), `sandbox.runner.latency` timer (`operation`). No id or text as a tag on either side.

Logs: JSON in production like the other Java services, MDC keys `tenant_id`, `workspace_id`, `subagent_run_id` for a run workspace and `conversation_id` for a chat workspace. INFO: workspace created and destroyed with reason, command finished with exit code, duration and output sizes, reaper removals. WARN: limit refusals, `workspace_busy`, destroy failures, the `runc` banner. DEBUG only: command text, outputs, file paths with contents. The proxy's own logs (allowed and denied host names) go to the container log, which `otel-collector` ships to Loki (it replaced `vector` by owner answer 89.12 of 2026-10-08), labelled with the workspace labels.

Traces: runner HTTP server spans through Spring Boot's OTLP export (same property names as `upgrade-spring-boot-4`), the agent's client spans are children of the run's `subagent.run` observation, or of the chat request's observation for a chat workspace.

`sandbox.reaper.removed` also counts the kinds `gateway`, `area-helper` and `image` and the reason `orphan_image`.

Startup banner of the runner: runtime of workspaces, the engine's default runtime, profiles with their digests, uses and `project-backed` marks, limits and maxima, reaper interval, whether the egress proxy and gateway images are present with the gateway digest, the coding area mode, host path, size and free percent when a `project-backed` profile is configured, the number of services and their reserved memory, and the number of integration secret variables present (never a name with its value).

### D14: Tests

- Runner unit tests: path validator (every rejection rule), container spec factory (forbidden settings never appear, D9, and the runtime of each container kind, D10), limit checks, label parsing, reaper decision table, token check in constant time, error mapping.
- Runner integration tests with Testcontainers' engine connection (runs on Docker Desktop with `runc` and on Linux with either runtime): full lifecycle, timeouts with background and `setsid` children, output truncation, busy rule, tmpfs size, process and memory limits, allow list through a real Smokescreen proxy to a local test HTTPS server whose name is allow-listed and to one that is not, reaper after a simulated crash (objects created and then the runner context restarted), cross-tenant 404.
- Escape suite (`./gradlew escapeTest`, its own source set and tag, runs against any engine): every scenario of the "isolated", "network" and "limits" requirements, plus `/proc/1/environ` and `/proc/self/status` checks, `ls /run/secrets`, mounts list must show no host path, attempts to reach the runner, the agent, `host.docker.internal`, the host's address on the default bridge network (the gateway that `docker network inspect bridge` prints, because on Linux Docker Engine the name `host.docker.internal` does not resolve in a container without an extra hosts entry, so a refusal by that name alone proves nothing there, `close-agent-test-gaps` D8), `169.254.169.254`, the other workspace's address and the Docker socket over TCP 2375 and 2376. With `-PexpectRuntime=runsc` the suite fails when the workspace does not run under gVisor (the kernel message check) instead of passing on `runc`, and also fails when the runner or the egress proxy runs under gVisor. Task 9.3 runs it that way on a Linux host and records the output.
- Agent unit tests: tools against the fake client for a run and for the main chat, tool list composition (main chat and runs, a tenant policy that allows each tool and one that does not), lifecycle listener for each final state, chat workspace close rules (idle, expiring, room needed, conversation gone), output upload limits.
- Agent integration tests: the `sandbox_workspace` migration on Testcontainers PostgreSQL, repository queries per tenant, the idle sweep and the two retention entries on the shared scheduler, each run twice to prove it is safe to repeat, and the room rule and the chat create race on two connections.
- Contract test: a Pact consumer test in the agent for the runner API (the repository already uses Pact for ascend-ocr) and the provider verification in the runner.
- Runner tests of D15 to D17: project folder create, size and delete, `project_busy`, the subpath mount of one project only, a link in a project pointing at another project or at `/` resolving inside the workspace only, the production refusals of the area, gateway route rendering, the secret not in any inspect output, path refusal and rate limit at the gateway, header not logged, the open mode of the proxy image, archive refusal, an image whose container never started, service create, replace and adopt, and secret resolution from the runner's environment.
- End-to-end: a new deterministic spec in `apps/ascend-agent/e2e/` (next free number at implementation time) on the scripted model of the shared e2e harness of `close-agent-test-gaps`, which forces every tool call, so no AI model is called (review item 30, owner answer 75.1 of 2026-10-07). The harness starts only for deterministic tests and never for AI-run e2e specs (owner answer 70.4 of 2026-10-04). Case 1: a subagent definition with `shell`, `file_write` and `file_read` writes and runs a script, writes `out/report.md`, and the test checks the run result, the archive through `GET /api/v1/runs/{id}/sandbox-output`, the workspace record `destroyed`, and no container or network left with the run's label on the Docker host. It is the one deterministic spec of this change (owner answer 91.3 of 2026-10-08): the runner suite with its probe image `ascend-e2e-bru:local` and the output endpoint refusal spec are removed, because the runner integration tests, the Pact test and the controller tests prove what they checked. Case 2: a run is cancelled and its workspace is gone. Case 3: the main chat writes a file in one turn and reads it in the next turn of the same conversation, and a second conversation does not see it.

### D15: Project-backed workspaces and the coding project area

Written on 2026-10-02 from the required edits 1, 2, 3, 5 and 6 of `add-coding-agent-delegation` (its D3 and D4). That change owns the agent side: coding projects, their states, the free space check and every cleanup decision. This change owns the runner side below.

Area and configuration (`app.runner.coding-area.*`):

- One named volume `ascend-coding-area` (`.volume`), created by the runner at startup when missing. In `host` mode (`.mode: host`) it is a `local` driver volume with `type=none`, `o=bind` and `device=<.host-path>`, so the files live in a host folder on a file system of its own and filling the area cannot fill the disk that Docker, PostgreSQL and the system use. `.host-path` comes from `CODING_AREA_HOST_PATH` (name approved by the owner in answer 44 of 2026-10-02), and in production it is a separate partition mounted at `/srv/ascend/coding` (same answer). In `volume` mode it is a plain named volume for development only: the runner logs one WARN banner line and reports `codingArea.mode: volume` in `/ready`, the same pattern as `runc` in D10.
- The area exists only for profiles marked `project-backed` (D7). When no such profile is configured, the runner neither creates nor checks the volume, so a deployment without the module `coding` needs no area and no host path.
- Startup checks when a `project-backed` profile is configured: the engine API version is at least 1.45 (Docker Engine 26.0, which added `VolumeOptions.Subpath`), the volume exists or is created, its driver options match the configured mode and host path, and a `df` through the helper below answers. Under the `production` profile the runner refuses to start in `volume` mode or with an empty host path. The banner shows the mode, the host path, the size and the free percent.
- Host setup: `infra/sandbox/coding-area/setup-coding-area.sh` (strict mode, ShellCheck clean, one argument for the host path), run once with `sudo` by the deployment guide. It creates the folder with owner 10002:10002 and mode 0700, prints a WARN when the folder is not a mount point of its own, and changes nothing on a second run.
- Layout: `tenants/<tenantId>/projects/<projectId>/` with `repo/`, `home/`, `tmp/`, `out/` and `run/` in each project folder, every file owned by the workspace user 10002. The tenant id is the tenant slug and the project id is a UUID. The runner keeps no record of projects: the folders are the record.

The project mount:

- A create for a `project-backed` profile carries `project: {id}`. A create for any other profile that carries `project` is refused with 400 `validation`. The runner adds one `Mounts` entry of type `volume`, source `ascend-coding-area`, target `/workspace`, read-write, with `VolumeOptions.Subpath = tenants/<tenant>/projects/<projectId>`, in place of the `/workspace` tmpfs of D4. The tenant comes from the `X-Ascend-Tenant` header, never from the body, and the subpath is built only from that validated slug and the validated UUID, never from a free path. `/tmp` stays a tmpfs. The workspace view reports `storage: project` (and `storage: tmpfs` for every other workspace).
- The daemon opens each part of the subpath without following symbolic links, so a link placed anywhere in the area cannot lead the mount out of the project folder. Inside the container a link resolves inside the container's own view, which holds only that project.
- A missing project folder answers 404 `project_not_found`. One workspace per project at a time: the workspace carries the label `ascend.sandbox.project=<projectId>`, and a create for a project that already has a live workspace answers 409 `project_busy`.
- The forbidden settings test of D9 allows a `volume` mount only for `ascend-coding-area`, only at `/workspace` with a subpath that matches `tenants/<slug>/projects/<uuid>` and only for a `project-backed` profile, and at `/area` only for an area helper. Every other mount still fails it.

Area operations run in a short-lived helper container (kind `area-helper` in the labels): the base profile image, the engine's default runtime, user 10002, no network, `CapDrop: ALL`, `no-new-privileges`, read-only root, only the area volume mounted at `/area`, removed when done, at most `.helper-timeout` (60 seconds), or `.archive-timeout` (30 minutes) for the archive call. It never runs project code.

| Runner endpoint | Helper command | Use |
| :--- | :--- | :--- |
| `POST /v1/coding-area/projects` body `{projectId}` | `mkdir -m 0700 -p -- /area/tenants/<t>/projects/<p>/{repo,home,tmp,out,run}` | Create a project folder before its first workspace |
| `GET /v1/coding-area` | `df -B1 --output=size,avail /area` | Total and free bytes and the free percent of the area, plus the mode |
| `GET /v1/coding-area/projects/{projectId}` | `du -sxB1 -- /area/tenants/<t>/projects/<p>` | Size of one project |
| `DELETE /v1/coding-area/projects/{projectId}` | `rm -rf --one-file-system -- /area/tenants/<t>/projects/<p>`, then a check that the path is gone | Remove a project folder. 409 `project_busy` when a workspace mounts it. `rm -rf` never follows a link out of the folder |
| `GET /v1/coding-area/projects/{projectId}/archive` | `tar -C /area/tenants/<t>/projects/<p> --one-file-system -czf - .`, streamed to the caller | The whole project folder as a gzip tar archive (`application/gzip`), for the user and tenant export of `add-audit-and-gdpr-compliance`. 409 `project_busy` when a workspace mounts it, so the archive is never taken from a folder in use. `tar` stores a symbolic link as a link and never follows it out of the folder |

All five are tenant scoped by the `X-Ascend-Tenant` header like every runner call, and answer 404 for a project folder of another tenant. The archive call is bounded by `.archive-timeout` (30 minutes) instead of `.helper-timeout`, because a project can be large, and the runner streams the archive without keeping a copy.

Source checked on 2026-10-02: https://docs.docker.com/engine/storage/volumes/ and https://github.com/moby/moby/pull/45687 (`VolumeOptions.Subpath`, Engine 26.0, API 1.45, the subfolder must exist, no link is followed), and `daemon/volume/local/local_unix.go` of `moby/moby` (`type`, `o` and `device` of the `local` driver).

### D16: The per-workspace credential gateway

Written on 2026-10-02 from the required edits 2, 4 and 5 of `add-coding-agent-delegation` (its D7) and the gateway part of edit 2 of `add-self-built-integrations` (its D9). A workspace never holds a credential of the platform. When a client needs authenticated calls, the runner starts one gateway container next to the workspace's egress proxy, and only the gateway holds the secret.

- Image: `infra/sandbox/credential-gateway/`, the official `nginxinc/nginx-unprivileged` image (nginx is BSD-2-Clause) pinned by digest, with a fixed config template and an entrypoint. The entrypoint renders nginx's config from a routes JSON in an environment variable that holds no secret, and includes each header value from `/run/gateway-secrets/<route>`. nginx forwards without buffering (`proxy_buffering off`, `proxy_request_buffering off`), verifies the upstream certificate with the right name (`proxy_ssl_verify on`, `proxy_ssl_server_name on`), sets one header per route, refuses every path that is not listed with 403, answers 429 above a route's rate per minute, and reloads on a signal. Its image reference is `app.runner.gateway.image`, checked at startup like the profile images (D7).
- Routes: each route has a name, a kind, an upstream origin, the paths it may forward, a header kind (`Authorization: Bearer`, `x-api-key`, `Authorization: Basic`, or none) and a rate per minute. Kind `credential` listens on port 8080 and forwards to its `https://` upstream. Kind `inbound` (asked for by `add-self-built-integrations`) listens on its own port 8081, forwards to one fixed container address on the gateway's internal network and adds no header. Each kind listens only on its own port. A workspace gateway has only `credential` routes. An upstream is never a private address unless it is listed in `app.runner.gateway.private-upstreams`, which is how an operator lets a local LM Studio (`http://host.docker.internal:1234`) be reached. When a route's upstream host is `host.docker.internal`, the runner creates that gateway with `ExtraHosts: ["host.docker.internal:host-gateway"]`, the Docker Engine API form of `--add-host`, so the name resolves on Linux Docker Engine too (Engine 20.10 or newer, `close-agent-test-gaps` D8, rule 3). No other gateway and no workspace gets an extra hosts entry (D9). On Linux the call arrives at the host's address on the default bridge network, so LM Studio is reached only while it listens on that address or on all addresses.
- Create body: `gateway: {routes: [...]}` on `POST /v1/workspaces`, each route with the fields above and its secret value. The workspace view lists the route names only, never an upstream secret.
- Secrets: the runner creates the gateway with no secret in its environment, command or labels, writes each secret through an exec with the value on standard input into `/run/gateway-secrets/<route>` (mode 0400, owned by the gateway user, on a 1 MiB tmpfs), then sends the reload signal. The runner keeps no copy, never logs the body of a create, and never returns a value.
- Container: kind `gateway` in the labels, the engine's default runtime (D10), non-root, `CapDrop: ALL`, `no-new-privileges`, read-only root, the 1 MiB secrets tmpfs and a small tmpfs for nginx temp files, 64 MiB memory, 0.25 CPU. For a workspace it joins the workspace's internal network with the network alias `gateway` and `sandbox-egress`, so every workspace uses the same base URL `http://gateway:8080`, and the workspace's `NO_PROXY` holds `gateway`. Create order is network, proxy, gateway, workspace, and destroy order is the reverse (D8).
- Logs: one access line per request with route, method, path without query, status, duration and bytes. No header, query or body is ever logged.
- The runner tests prove that the alias `gateway` resolves under `runc`. `add-coding-agent-delegation` task 9.2 proves it under `runsc`, and that change's D7 holds the fallback if it does not.

### D17: Integration images and integration services

Written on 2026-10-02 from the required edits 1 to 7 of `add-self-built-integrations` (its D7, D8, D9 and D11). That change owns the agent side: building, testing, approving and reconciling integrations. This change owns the runner side below.

Images (`add-self-built-integrations` D7). An integration image is assembled by the engine without running any code:

- `POST /v1/images`, multipart with `profile` (a profile marked `use: image`, D7), the `X-Ascend-Tenant` header, `integrationId`, `version`, `source` (tar) and `deps` (tar).
- The runner validates each archive while it streams it to its tmpfs with Apache Commons Compress: only regular files and folders, relative paths with no `..`, no absolute path, no NUL, at most 1024 bytes per path, no set-user-id or set-group-id bit, at most `app.runner.images.max-entries` (5000) entries and `app.runner.images.max-bytes` (60 MiB) together. A refused archive answers 400 `archive_refused`. It computes and returns the SHA-256 of each archive.
- It creates a container from the profile's pinned image with `NetworkMode: none` and the image labels, never starts it, extracts `source` into `/app/src` and `deps` into `/app/deps` with `noOverwriteDirNonDir=true` (files owned by root, so user 10003 can read and never change them), commits it with repository `ascend-integration/<tenant>-<first 12 hex of the integration id>`, tag `v<version>`, `pause=false`, and a fixed config (`User` 10003, `Cmd`, `Env` with `PYTHONPATH` only, the labels `ascend.sandbox=true`, `ascend.sandbox.kind=image`, tenant, integration and version), removes the container and answers 201 with the image id, its size and the two digests.
- `DELETE /v1/images/{imageId}` removes an image after the tenant label check. At most `app.runner.images.max-per-integration` (2) images are kept per integration.

Services (`add-self-built-integrations` D8 and D9). A service is a long-lived integration container with its own network `ascend-int-<id>` (`internal: true`), its own egress proxy and its own gateway:

| Method and path | Body | Answer |
| :--- | :--- | :--- |
| `PUT /v1/services/{id}` | `imageId`, `limits`, `egress.allow` (hosts), `gateway.routes` (each credential route names its credential, never a value), `ingressAlias` | 200 service view. Creates or replaces, so the observed state equals the body |
| `GET /v1/services` | | The calling tenant's services |
| `GET /v1/services/{id}` | | View with `state`, `health`, `restartCount`, `specDigest`, `startedAt` and `secretPresent` per credential route |
| `DELETE /v1/services/{id}` | | 204. Removes the container, the gateway, the proxy and the network. 404 `service_not_found` for an unknown service or one of another tenant |

- The runner compares the SHA-256 of the canonical body plus a digest of each secret value it read from its environment with the label `ascend.sandbox.spec-digest`, and recreates only the parts that changed: a new image replaces the integration container, a new egress list replaces the proxy, and a new route or a changed secret value rewrites the gateway's secret files and reloads nginx.
- An egress proxy is recreated, never reloaded, when its allow list changes, because Smokescreen ends on `SIGHUP` (D6).
- The integration container follows the workspace settings of D4 (non-root user 10003, `CapDrop: ALL`, `no-new-privileges`, read-only root, the configured runtime, `runsc` in production, no `Binds`, no `Mounts`, a DNS server that does not answer), plus a 32 MiB `/tmp` tmpfs, `RestartPolicy: on-failure` with at most 3 tries and the image's health check. Limits default to 0.25 CPU, 256 MiB and 128 processes, with maxima 1.0 CPU, 1024 MiB and 512 processes. Its proxy and its gateway take 0.1 CPU, 64 MiB and 64 processes each. Services do not count against `max-workspaces`, and there is no count limit on services (owner decision 40.4 of 2026-10-02). The runner reports the reserved memory of all services as `sandbox.services.reserved.memory`.
- Networks: the integration container joins only `ascend-int-<id>`, with `HTTPS_PROXY` and `HTTP_PROXY` pointing at its proxy's address and `NO_PROXY=gateway`. The proxy joins `ascend-int-<id>` and `sandbox-egress` in `enforce` mode, and an empty list allows nothing. The gateway (D16) joins `ascend-int-<id>`, `sandbox-egress` and `integrations-ingress`, with the alias `int-<first 12 hex of the id>` on the last one. Its `inbound` route on port 8081 forwards `/mcp` and `/health` to `http://integration:8000`, and its credential routes listen on port 8080.
- `integrations-ingress` is a network declared in `compose.yaml` with `internal: true`. The agent joins it and the runner attaches gateways to it. Only the agent and gateways are on it, so neither an integration nor a gateway can reach the agent's port through it.
- Credentials of a service come only from the runner's own secrets file (D9). The body names, per credential route, only the credential. The runner derives the variable name itself, reads the value at that moment, writes it into the gateway's tmpfs as in D16, and reports only `secretPresent`. A route whose variable is missing or empty is not created.
- At startup the runner adopts every existing service by its labels before it reports ready, so recreating the runner (for example after a new line in the secrets file) never stops a running integration.

### D18: Settings (owner rule 98 of 2026-10-08)

Every value of this change that has a default is a setting. The runner and the agent are Spring Boot services: the property keeps its `app.*` name, `application.yaml` writes `key: ${ENV:default}`, the `@ConfigurationProperties` record carries the same default, and the compose service writes `- ENV=${ENV:-default}`. ENV is Spring Boot's canonical environment form of the property (upper case, dots become underscores, hyphens removed), unless a name was already decided. A secret has no default and keeps its `:?` guard. Rows go into `docs/CONFIGURATION.md` for the runner, the egress proxy and the credential gateway, and into `apps/ascend-agent/docs/CONFIGURATION.md` for the agent, with "Added by `add-agent-sandbox`." (at the end of the description in the per-service file, in the Added by column of `docs/CONFIGURATION.md`, which `fix-linux-docker-host-access` creates in build group 1).

Runner (`ascend-sandbox-runner`), tasks 2.2, 7.2 and 7.8:

| Property | Environment variable | Default |
| :--- | :--- | :--- |
| `server.port` | `SANDBOX_RUNNER_PORT` | `9940` |
| `app.runner.token` | `SANDBOX_RUNNER_TOKEN` | none, secret, `:?` guard |
| `app.runner.runtime` | `SANDBOX_RUNTIME` | `runsc` |
| `app.runner.limits.cpus` and `app.runner.maxima.cpus` | `APP_RUNNER_LIMITS_CPUS` and `APP_RUNNER_MAXIMA_CPUS` | `1.0` and `2.0` |
| `app.runner.limits.memory-mib` and `app.runner.maxima.memory-mib` | `APP_RUNNER_LIMITS_MEMORYMIB` and `APP_RUNNER_MAXIMA_MEMORYMIB` | `1024` and `4096` |
| `app.runner.limits.workspace-mib` and `app.runner.maxima.workspace-mib` | `APP_RUNNER_LIMITS_WORKSPACEMIB` and `APP_RUNNER_MAXIMA_WORKSPACEMIB` | `512` and `2048` |
| `app.runner.limits.pids` and `app.runner.maxima.pids` | `APP_RUNNER_LIMITS_PIDS` and `APP_RUNNER_MAXIMA_PIDS` | `256` and `1024` |
| `app.runner.limits.ttl` and `app.runner.maxima.ttl` | `APP_RUNNER_LIMITS_TTL` and `APP_RUNNER_MAXIMA_TTL` | `30m` and `2h` |
| `app.runner.limits.command-timeout` and `app.runner.maxima.command-timeout` | `APP_RUNNER_LIMITS_COMMANDTIMEOUT` and `APP_RUNNER_MAXIMA_COMMANDTIMEOUT` | `120s` and `900s` |
| `app.runner.limits.tmp-mib` | `APP_RUNNER_LIMITS_TMPMIB` | `64` |
| `app.runner.limits.output-bytes` | `APP_RUNNER_LIMITS_OUTPUTBYTES` | `65536` |
| `app.runner.limits.file-read-bytes` | `APP_RUNNER_LIMITS_FILEREADBYTES` | `1048576` (1 MiB) |
| `app.runner.limits.file-write-bytes` | `APP_RUNNER_LIMITS_FILEWRITEBYTES` | `4194304` (4 MiB) |
| `app.runner.limits.archive-bytes` | `APP_RUNNER_LIMITS_ARCHIVEBYTES` | `52428800` (50 MiB) |
| `app.runner.limits.max-workspaces-per-tenant` | `APP_RUNNER_LIMITS_MAXWORKSPACESPERTENANT` | `4` |
| `app.runner.limits.max-workspaces` | `APP_RUNNER_LIMITS_MAXWORKSPACES` | `4` |
| `app.runner.reaper-interval` | `APP_RUNNER_REAPERINTERVAL` | `60s` |
| `app.runner.commands.kill-after` | `APP_RUNNER_COMMANDS_KILLAFTER` | `2s` |
| `app.runner.commands.wait-margin` | `APP_RUNNER_COMMANDS_WAITMARGIN` | `5s` |
| `app.runner.profiles.base.image` | `APP_RUNNER_PROFILES_BASE_IMAGE` | the base image digest written by task 5.3 |
| `app.runner.egress.image` | `APP_RUNNER_EGRESS_IMAGE` | the egress proxy image digest written at implementation time (task 4.1) |
| `app.runner.egress.network` | `APP_RUNNER_EGRESS_NETWORK` | `sandbox-egress` |
| `app.runner.egress.port` | `APP_RUNNER_EGRESS_PORT` | Smokescreen's own default listen port, read in its source at implementation time (task 4.1) |
| `app.runner.egress.memory-mib` | `APP_RUNNER_EGRESS_MEMORYMIB` | `64` |
| `app.runner.egress.cpus` | `APP_RUNNER_EGRESS_CPUS` | `0.25` |
| `app.runner.egress.max-allow-entries` | `APP_RUNNER_EGRESS_MAXALLOWENTRIES` | `32` |
| `app.runner.gateway.image` | `APP_RUNNER_GATEWAY_IMAGE` | the gateway image digest written at implementation time (task 10.5) |
| `app.runner.gateway.memory-mib` | `APP_RUNNER_GATEWAY_MEMORYMIB` | `64` |
| `app.runner.gateway.cpus` | `APP_RUNNER_GATEWAY_CPUS` | `0.25` |
| `app.runner.gateway.secrets-tmpfs-mib` | `APP_RUNNER_GATEWAY_SECRETSTMPFSMIB` | `1` |
| `app.runner.gateway.temp-tmpfs-mib` | `APP_RUNNER_GATEWAY_TEMPTMPFSMIB` | not decided (the "small tmpfs for nginx temp files" of D16 names no size) |
| `app.runner.gateway.private-upstreams` | `APP_RUNNER_GATEWAY_PRIVATEUPSTREAMS` | empty |
| `app.runner.coding-area.mode` | `APP_RUNNER_CODINGAREA_MODE` | not decided (D15 names `host` for production and `volume` for development only) |
| `app.runner.coding-area.host-path` | `CODING_AREA_HOST_PATH` (owner answer 44) | empty |
| `app.runner.coding-area.volume` | `APP_RUNNER_CODINGAREA_VOLUME` | `ascend-coding-area` |
| `app.runner.coding-area.helper-timeout` | `APP_RUNNER_CODINGAREA_HELPERTIMEOUT` | `60s` |
| `app.runner.coding-area.archive-timeout` | `APP_RUNNER_CODINGAREA_ARCHIVETIMEOUT` | `30m` |
| `app.runner.images.max-entries` | `APP_RUNNER_IMAGES_MAXENTRIES` | `5000` |
| `app.runner.images.max-bytes` | `APP_RUNNER_IMAGES_MAXBYTES` | `62914560` (60 MiB) |
| `app.runner.images.max-per-integration` | `APP_RUNNER_IMAGES_MAXPERINTEGRATION` | `2` |
| `app.runner.images.orphan-age` | `APP_RUNNER_IMAGES_ORPHANAGE` | `1d` |
| `app.runner.services.limits.cpus`, `.memory-mib` and `.pids` | `APP_RUNNER_SERVICES_LIMITS_CPUS`, `_MEMORYMIB` and `_PIDS` | `0.25`, `256` and `128` |
| `app.runner.services.maxima.cpus`, `.memory-mib` and `.pids` | `APP_RUNNER_SERVICES_MAXIMA_CPUS`, `_MEMORYMIB` and `_PIDS` | `1.0`, `1024` and `512` |
| `app.runner.services.sidecar.cpus`, `.memory-mib` and `.pids` (the proxy and the gateway of a service) | `APP_RUNNER_SERVICES_SIDECAR_CPUS`, `_MEMORYMIB` and `_PIDS` | `0.1`, `64` and `64` |
| `app.runner.services.tmp-mib` | `APP_RUNNER_SERVICES_TMPMIB` | `32` |
| `app.runner.services.restart-max-tries` | `APP_RUNNER_SERVICES_RESTARTMAXTRIES` | `3` |
| compose memory limit of the runner container | `SANDBOX_RUNNER_MEMORY_LIMIT` (compose only) | `512M` |

The agent's base URL default `http://ascend-sandbox-runner:9940` names the runner port, so changing `SANDBOX_RUNNER_PORT` also needs `APP_SANDBOX_RUNNER_BASEURL`. `server.port` gets the named variable `SANDBOX_RUNNER_PORT` instead of `SERVER_PORT`, because compose fills `${VAR}` from the one root `.env` for every service, so a generic name would move other services too. The egress proxy and the credential gateway read only what the runner passes them when it creates them (`ALLOWED_HOSTS`, the listen port, the routes JSON), so they need no compose line. The proxy image's entrypoint reads its listen port from the environment variable `EGRESS_PROXY_PORT`, whose default in the entrypoint is the same Smokescreen default, and the runner passes `app.runner.egress.port` as that variable and uses it in `HTTP_PROXY` and `HTTPS_PROXY` (D4).

Agent (`ascend-agent`), task 8.15:

| Property | Environment variable | Default |
| :--- | :--- | :--- |
| `app.sandbox.runner.base-url` | `APP_SANDBOX_RUNNER_BASEURL` | `http://ascend-sandbox-runner:9940` in the `docker` profile and on the compose line. The default of the host run (`bootRun`) is not decided, because the runner publishes no port |
| `app.sandbox.runner.token` | `SANDBOX_RUNNER_TOKEN` | none, secret, `:?` guard |
| `app.sandbox.runner.connect-timeout` | `APP_SANDBOX_RUNNER_CONNECTTIMEOUT` | `2s` |
| `app.sandbox.runner.read-timeout-margin` | `APP_SANDBOX_RUNNER_READTIMEOUTMARGIN` | `10s` |
| `app.sandbox.run-ttl-margin` | `APP_SANDBOX_RUNTTLMARGIN` | `60s` |
| `app.sandbox.profile` | `APP_SANDBOX_PROFILE` | `base` |
| `app.sandbox.limits.cpus`, `.memory-mib`, `.workspace-mib`, `.pids`, `.command-timeout` | `APP_SANDBOX_LIMITS_CPUS`, `_MEMORYMIB`, `_WORKSPACEMIB`, `_PIDS`, `_COMMANDTIMEOUT` | not decided (D11 says only "lower than or equal to the runner's maxima") |
| `app.sandbox.network.allow` | `APP_SANDBOX_NETWORK_ALLOW` | empty |
| `app.sandbox.network.max-allow-entries` | `APP_SANDBOX_NETWORK_MAXALLOWENTRIES` | `32` |
| `app.sandbox.output.bucket` | `APP_SANDBOX_OUTPUT_BUCKET` | `sandbox-output` |
| `app.sandbox.output.max-bytes` | `APP_SANDBOX_OUTPUT_MAXBYTES` | not decided (D11 names the key, no value) |
| `app.sandbox.chat.idle-timeout` | `APP_SANDBOX_CHAT_IDLETIMEOUT` | `30m` |
| `app.sandbox.chat.max-lifetime` | `APP_SANDBOX_CHAT_MAXLIFETIME` | `2h` |
| `app.sandbox.chat.max-open-per-tenant` | `APP_SANDBOX_CHAT_MAXOPENPERTENANT` | `2` |
| `app.sandbox.chat.output-retention` | `APP_SANDBOX_CHAT_OUTPUTRETENTION` | `30d` |
| `app.scheduler.system-tasks.sandbox-chat-idle-sweep.cron` and `.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_SANDBOXCHATIDLESWEEP_CRON` and `APP_SCHEDULER_SYSTEMTASKS_SANDBOXCHATIDLESWEEP_TIMEZONE` (`add-shared-scheduler` D2) | `*/5 * * * *` and `UTC` |

`app.sandbox.network.tenant-allow.<tenant>` is a map keyed by tenant slug with no default, so it gets no compose line, and an operator sets an entry in `application.yaml` or with the explicit placeholder he writes there. The "near expiry" margin of a chat workspace (two sweep intervals, D11) stays derived from the sweep's cron.

Kept as constants, because they are not operational: the workspace users 10001, 10002 and 10003 (identities baked into the images), the path rules of D5 and D17 (the 1024 byte path cap, no `..`, no NUL, no leading `-`, a format rule of the validator), the gateway listen ports 8080 and 8081 and the integration container port 8000 (fixed inside images this change builds, never published and never reached from outside the workspace's own network), the network alias `gateway`, the label names of D8, the network and container name patterns `ascend-sbx-<id>` and `ascend-int-<id>`, the volume subpath layout of D15, the engine API minimum 1.45 (a version), the problem codes and the metric names. Image digests are versions, set only through the profile and image settings above.

## Required edits to other changes

This change edits no other change. Each edit below belongs to the named change.

### `add-deployment-modules`

By owner decision of 2026-10-03 (owner answer 52) the sandbox is core, always on and never switchable. Edits 1 to 4 are made in that change, checked on 2026-10-03 (its D3 catalog and core list, its D11 compose guard rules and its sections for this change and for `add-coding-agent-delegation`):

1. Remove the catalog entry `sandbox` and its tenant module grant, and remove `profiles: [sandbox]` from `ascend-sandbox-runner`, so the runner runs in every deployment. Drop `sandbox` from every preset and from the module lists of its design.
2. List the classes of `service/sandbox/`, `SandboxOutputController` and `SandboxProperties` in the `core-chat` list of `ModuleMarkingCoverageTest`, with no `@ConditionalOnModule`, and drop `module_denied` for the sandbox tools and output routes.
3. `SANDBOX_RUNNER_TOKEN` leaves the module secret check and becomes a required secret of every deployment, guarded with `${SANDBOX_RUNNER_TOKEN:?...}` in compose.
4. The entry `coding` no longer requires `sandbox`, and no other entry names it.

Still true there and followed here: `app.sandbox.enabled` is removed (D11).

### `add-shared-scheduler`

1. The closed enum `SchedulerTaskName` gains `sandbox-chat-idle-sweep`, registered in every deployment, because the sandbox is core (owner decision of 2026-10-03, D11). The runner's reaper is not a system task (D8). Made in that change: its required edit for this change and its job inventory, where the module column reads `core-chat` and the zone `UTC`.
2. Owner answers 89.7 and 93 of 2026-10-08: the retention is the two entries `sandbox-run-workspaces` and `sandbox-chat-workspaces` of its shared retention task `record-retention` with an archive cleanup hook (made there, its job inventory), and `sandbox-destroy-retry` is removed (D11). Its job inventory row and enum value of `sandbox-destroy-retry` go away, sent on 2026-10-08 through `inbox93/add-shared-scheduler__from__add-agent-sandbox.md`.

### `add-agent-subagents`

Made in that change on 2026-10-02:

1. Design D9 and D9a: the sandbox tool names are `shell`, `file_read` and `file_write`, and the `SandboxClient` port is named there, so its WARN for unavailable tools uses the same names.
2. The run's `RunContext` gains one optional field for the sandbox workspace id, read and written only by this change's service (its D8).
3. Its restart sweep (D14) publishes `SubagentRunChangedEvent` for every run it closes, so this change destroys their workspaces through the same listener.
4. By owner decision 21.6 of 2026-10-02, design D9a and its tool context: the sandbox tools are offered to the main chat too, in a workspace of its own per conversation that is never shared with a run, and a subagent run still gets its own workspace and never the conversation's.

### `add-tenant-policy`

Since the fix of 2026-10-05 that change registers its allow-list as the implementation of the `TenantToolPolicy` port of `add-agent-skills`, and adding the three names to the deployment default policy is a task of that change.

1. `shell`, `file_read` and `file_write` are new tools and ship off for a new tenant. The deployment default policy of the personal deployment (`app.policy.default.*`) lists all three (owner decision of 2026-10-02), so a single owner install can use them in the main chat and in subagent runs. Made in that change (its tool table in design D8). After the owner decision of 2026-10-03 made the sandbox core, the tenant policy stays the per tenant switch of the three tools.
2. Its `tool-policy` spec no longer grants `sandbox` as a module: the scenario of a grant set not closed under requires uses `subagents` and `skills`, the sandbox is never answered `module_denied`, and the shell tools are turned off for one tenant as tools. Made in that change, checked on 2026-10-03.

### `add-tenant-isolation`

1. List `sandbox_workspace.tenant_id` with the other tenant columns and the object store prefix `tenant/<tenantId>/sandbox-output/` in the `sandbox-output` bucket with the other tenant scoped stores. Made in that change (its design, its `tenant-isolation` spec, the foreign key of `sandbox_workspace.tenant_id` to `tenants(id)` in its migration, and its task 3.9).

### `harden-cloud-deployment`

1. Its container hardening requirement lists `ascend-sandbox-runner` as the one service allowed to mount the Docker socket for sandbox work, beside the existing observability services, and states that a read-only socket mount is not a restriction.
2. `docs/DEPLOYMENT.md` "one cloud VM per customer" gains the `runsc` install and `DOCKER_SOCKET_GID` steps written by task 7.5 of this change, including the rule that `runsc` is never the engine's default runtime.

Both made in that change (its design, its `production-deployment` spec and its tasks 10.3 and 10.4).

### `add-usage-metering-and-quotas`

By owner decision of 2026-10-02 sandbox time is its own metered operation type. All three made in that change (its `usage-metering` spec, its design D12 and its task 9.2). Since the fix of 2026-10-05 the agent publishes the event through `UsageEventPort` (D11) and the ledger row is written by that change's implementation, in its own task:

1. `specs/usage-metering/spec.md`, first requirement (line 7): add `sandbox` to the closed list of request types, with `processing_ms` holding the time a workspace existed, and a scenario that a destroyed workspace of a run writes one `sandbox` row for the run's tenant and user, and that a destroyed chat workspace writes one for the conversation's tenant and user with no run id.
2. Its "Every service operation the agent calls is metered by the agent" requirement and design D12: the agent records one `sandbox` row per destroyed workspace, and a workspace whose create failed writes no row.
3. Design D11 and D12: `sandbox` joins the closed set of request types, which is also the set of `request_type` tag values.

### `add-audit-and-gdpr-compliance`

1. User erasure includes the user's `sandbox_workspace` rows and their output archives, found through each row's `output_key`, and destroys any open workspace of the user first.
2. Tenant erasure deletes every `sandbox_workspace` row of the tenant and every object under `tenant/<tenantId>/sandbox-output/` in the `sandbox-output` bucket.

Both made in that change (its design, its `data-erasure` spec and its erasure task).

### `add-customer-stack-installer`

By owner decision of 2026-10-03 the sandbox is core, so its token is needed in every deployment. Not made here:

1. Design D4: `SANDBOX_RUNNER_TOKEN` (at least 32 characters) is always generated, like `SEARXNG_SECRET`, because its compose `:?` guard needs it in every deployment, and `DOCKER_SOCKET_GID` is measured on the host and written to `.env`.

### Applied here from other changes

Written into this change on 2026-10-02. Each source change marks its edit as made in its own text:

- `add-coding-agent-delegation` edits 1 to 7: project-backed profiles and the project mount (D4, D7, D9, D15), the create body fields `project` and `gateway`, the view fields `storage` and `gateway` and the codes `project_busy` and `project_not_found` (D3, D15, D16), the coding area endpoints done by the `area-helper` container (D15), secrets of a gateway sent in the create body and written only through exec standard input (D9, D16), the kinds `gateway` and `area-helper`, the label `ascend.sandbox.project`, the create and destroy order, the reaper rules, the alias `gateway` and `NO_PROXY` (D4, D8, D16), the configuration `app.runner.coding-area.*` with its startup checks and profile attributes for the `coding` profile that change adds (D7, D15), and the metrics and banner lines (D13).
- `add-coding-agent-delegation` edit 8, written here on 2026-10-03: the coding area endpoint `GET /v1/coding-area/projects/{projectId}/archive`, which streams one project folder as a gzip tar archive for the user and tenant export, with `project_busy` and `.archive-timeout` (D15).
- `add-self-built-integrations` edits 1 to 7: `POST /v1/images` and `DELETE /v1/images/{id}` with `archive_refused` (D17), the `/v1/services` API with its network, proxy, gateway, labels, reaper rules and adoption at startup (D8, D17), the profile attribute `use` for `integration-runtime` and `integration-verify` (D7), the proxy recreated and never reloaded (D6), the runner metrics including `sandbox.services.reserved.memory` (D13), the compose network `integrations-ingress` (D17), and the integration secrets from `integration-secrets.env` by owner answer 46.2 (D9, D17).
- `add-mcp-tool-servers` edit 1: the open mode `ALLOWED_HOSTS=*` of the egress proxy image, which keeps the private address refusal (D6).

## Risks / Trade-offs

- [A gVisor bug lets a workload reach the host kernel] → defence in depth: non-root, no capabilities, read-only root, default seccomp, no network, no secrets, short lifetimes. Keep `runsc` updated (weekly releases, apt repository). Move to Kata if the host gains KVM.
- [The runner is compromised and uses the socket] → small code, no inbound route except the token, no own internet, no published port, the forbidden-settings unit test, and the token only in `.env`.
- [The development runtime `runc` gives a false sense of safety] → WARN banner, metric tag, readiness field, and the production profile refuses it.
- [A tool needs a system call gVisor lacks] → the base image is tested under `runsc` (task 9.3), and the failure shows as a command error the model can see.
- [tmpfs workspace eats memory] → workspace size is part of the memory limit and checked at startup and create. Disk-backed workspaces are the `project-backed` profiles of D15, which mount one folder of the shared coding project area.
- [The coding project area fills up] → it sits on its own file system in production, so the rest of the server keeps working, and `add-coding-agent-delegation` checks its free space and asks the owner before any cleanup.
- [The runner holds integration secrets in its environment] → accepted by owner answer 46.2: they come only from `integration-secrets.env`, never from the root `.env`, are read only by a name the runner derives itself, and are written only into a gateway's tmpfs. A new or changed value needs a recreate of the runner, and running services are adopted by their labels.
- [A gateway bug hands a secret to the wrong workspace] → one gateway per workspace or service, never shared, the same reason as one proxy per workspace (D6).
- [Data exfiltration through an allowed host] → allow lists come only from configuration, never from the model, and are empty by default. A tenant that allows `github.com` accepts that a run can push to it.
- [DNS exfiltration] → name lookups from workspaces fail in both modes, checked by the escape suite.
- [Prompt injection runs harmful commands] → it can only harm its own workspace, which is destroyed at run end, or for the main chat when the conversation's workspace is closed. A chat workspace lives longer than a run workspace (at most 2 hours by default), so an injected command in one turn can affect later turns of the same conversation, and only that conversation.
- [Chat workspaces hold places that subagent runs need] → at most `chat.max-open-per-tenant` (2) per tenant, idle close after 30 minutes, and the least recently used one is closed when a new conversation needs room.
- [Two runner instances would reap each other's workspaces] → one runner per Docker host, shared by every agent copy on that host (owner answer 98.9 of 2026-10-08), written in the README. Every workspace state the agent needs lives in `sandbox_workspace`, and each row names its runner, so every later call reaches the runner that created the workspace (D11, D12).
- [The OpenSandbox project matures and would replace the runner] → the agent depends only on its `SandboxClient` port, so a second adapter can replace the runner later.
- [A migration number clashes with a sibling change] → `<n>` is taken at implementation time after the migrations already in the folder, and Flyway refuses a duplicate version at start-up.

## Migration Plan

1. Land as build group 4, position 3 of the owner build order of 2026-10-04, after build group 3 and after `add-agent-skills` and `add-agent-subagents`.
2. Production host: install `runsc` from the gVisor apt repository, run `sudo runsc install`, reload Docker, confirm with `docker info` that `runsc` is listed and that the default runtime is still `runc`, and run `docker run --rm --runtime=runsc hello-world`.
3. Set `SANDBOX_RUNNER_TOKEN` and `DOCKER_SOCKET_GID` in `.env` (and `SANDBOX_RUNTIME=runc` on Docker Desktop only), then `docker compose up -d --build`. The runner has no compose profile, so it starts in every deployment. When the module `coding` will be used, the production host first gets the coding project area: a separate partition mounted at `/srv/ascend/coding` (owner answer 44), `infra/sandbox/coding-area/setup-coding-area.sh` run once with that path, and `CODING_AREA_HOST_PATH` in `.env`. The file `integration-secrets.env` is optional and needed only by `add-self-built-integrations`.
4. Flyway applies the versioned migration that creates `sandbox_workspace` when the agent starts, in every deployment. The tools, routes and system tasks exist in every deployment. The default of the `TenantToolPolicy` port allows the three tools while `app.tool-policy.denied-tools` is empty. Once `add-tenant-policy` registers its implementation, any tenant other than the personal deployment needs its tool policy to allow them.
5. Rollback: the sandbox is core and has no switch. To stop its use without a release, list `shell`, `file_read` and `file_write` in `app.tool-policy.denied-tools` of `add-agent-skills` and restart the agent, or, once `add-tenant-policy` is applied, remove them from the tenant tool policies (runs and chat keep working without them). Rolling the change itself back means deploying the agent and `compose.yaml` of the release before this change and running `docker compose up -d --remove-orphans`, which removes the runner container. Workspaces left behind are removed by the runner's reaper on its next start, or by a force remove of the containers and networks labelled `ascend.sandbox=true`. The table stays and is ignored. Flyway runs forward only, so dropping it is a new versioned migration, written only if the owner asks for it.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fix of every item of the review of the group 3, 4 and 5 changes of 2026-10-07. Fixed here: item 7 (task 11.3 expects `limit_too_high`), item 23 (`sandbox_workspace.conversation_id` is a `UUID`, like `subagent_run.conversation_id`), item 25 (the overlay users `frostySandboxChatTest` and `frostySandboxChatOtherTest` are added by task 9.5), item 30 (the spec of task 9.5 is deterministic on the scripted model, and this change has no AI-run spec) and item 64 (`traceId` in the problem body field lists of D3 and the runner spec).

## Owner decisions of 2026-10-08

Answer 76.3 (partly): the Bruno request names `sandbox-scripted*` of the scripted spec of task 9.5 stay as they are. The answer keeps only the names, not their folders.

Answer 76.6: `sandbox_workspace.conversation_id` gets the same foreign key to `conversations(id)` and the same delete rule as `subagent_run.conversation_id` of `add-agent-subagents` (checked on 2026-10-08 in its D13, task 2.1 and `subagent-run-status` spec: the key `fk_subagent_run_conversation` with no delete action, and the conversation delete settles the conversation's runs and deletes their rows in the same transaction as the history). Here the key is `fk_sandbox_workspace_conversation` with no delete action. The conversation delete closes the open chat workspace with reason `CONVERSATION_GONE`, deletes every `sandbox_workspace` row of the conversation in the same transaction as its history, and deletes their archives after the commit (D11, D12, tasks 8.3, 8.7, 8.8 and 8.13, `specs/agent-sandbox-tools/spec.md`). The idle sweep no longer looks for deleted conversations, and the retention task no longer deletes records of deleted conversations, because none are left.

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/sandbox/` (task 9.5, spec `agent-sandbox-tools`). Every check that read the request journal now reads the scripted model's request log, `GET /mockoon-admin/logs` of the Mockoon admin API, and clears it with `POST /mockoon-admin/state/purge`.

Answer 77.2 (accepted): when the conversation delete of D11 cannot delete a saved archive after the commit, it logs a WARN line and the delete still succeeds (task 8.13).

Answer 77.3: the names `fk_sandbox_workspace_conversation` and `SandboxConversationDeleteIT` and the task number 8.13 stay.

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 9.5, which already wiped and now names the call). (Superseded by answer 91.1 below.)

Answer 81.3, addition (mandatory): every host and port of this change follows the rules of `close-agent-test-gaps` D8, so the plan works on Linux Docker Engine, where `host.docker.internal` does not resolve by itself. Checked on 2026-10-08: a gateway whose route names `host.docker.internal` (a local LM Studio listed in `app.runner.gateway.private-upstreams`) is created with `ExtraHosts: ["host.docker.internal:host-gateway"]`, and no other container of the runner gets an extra hosts entry (D16, task 10.6). The escape suite and the scenario "Internal services stay unreachable" also try the host's address on the default bridge network, because the name alone does not resolve on Linux (D14). The probe container of task 11.3 reached the runner by its service name on the stack's network (rule 1), which `docker network ls` showed as `ascend-ai_default` on 2026-10-08 (task 11.3 is removed by answer 91.3). The other `docker run` commands of this change (the set-user-id check of task 5.1, the socket group check of task 7.3 and the `runsc` check of task 7.5) call no other service and need no host mapping (rule 5). The mentions of Docker Desktop describe the development engine and name no address.

Answer 84.4 (F6): task 7.2 uses `group_add: ["${DOCKER_SOCKET_GID:-0}"]` for `ascend-sandbox-runner`, the same setting and default as `container-metrics-exporter` in `fix-linux-docker-host-access` task 3.1 (build group 1, position 4), instead of the empty default. Task 7.3 points at that group 1 task, which already adds the `.env.example` line with its comment and the Linux host prerequisite, instead of repeating it (tasks 7.2 and 7.3).

Answer 85.1: every key and secret lives in the repository `.env`, never in the shell. `SANDBOX_RUNNER_TOKEN` comes from `.env` through compose, and no plan text of this change exports a secret. The removed runner suite passed the token to its probe through `docker run -e`, and that step is gone with it (answer 91.3).

Answer 87 (rule R1, CANON 26.1): several agent instances run at once and share the one runner. Kept: the runner's per-workspace lock and its single instance per Docker host (D5, D8), the conditional state moves of `sandbox_workspace`, the partial unique index of the open chat workspace, the lifecycle listener and the idle sweep on the shared scheduler. Changed: a chat workspace create race between two instances is settled by that unique index and the loser uses the winner's row, the room rule takes the tenant's transaction-level advisory lock, and an unreachable runner's record is closed by the cluster-wide idle sweep instead of a second task (D11). Not decided here: whether the runner itself must run as several instances. It holds the Docker socket and its per-workspace lock and reaper assume one runner per Docker host, so making it multi-instance would need a shared lock between runners. Listed for the owner. (Settled by answer 98.9 below: one runner per Docker host.)

Answer 88 (rule R2): every company plug-in point and feature stays: egress per workspace (one proxy and one gateway per workspace or service, D6, D16), the image builder of D17, per-tenant workspace limits, the tenant label on every runner object, `UsageEventPort` and the `TenantToolPolicy` port.

Answer 89.7: workspace retention is two entries, `sandbox-run-workspaces` and `sandbox-chat-workspaces`, of the one shared retention task `record-retention` of `add-shared-scheduler`, with their archive cleanup hooks, and this change has no retention task of its own (D12, task 8.8).

Answer 89.10: the base requirement "Credentials flow from the environment with a production startup guard" of `harden-cloud-deployment` changed to the one production startup guard `ProductionStartupGuard` of `add-keycloak-login` with `application-production.yaml`, and this change's MODIFIED copy in `specs/production-deployment/spec.md` carries the new base text plus its own sandbox runner token lines. This change adds no production startup refusal of its own: `SANDBOX_RUNNER_TOKEN` stays a compose `:?` guard and a refusal of an empty token in `SandboxProperties` in every profile.

Answer 89.12: Vector is removed by `add-observability`, and `otel-collector` mounts the Docker socket in its place, so the services that may mount the socket are `otel-collector`, `container-metrics-exporter` and `ascend-sandbox-runner` (Context, `specs/production-deployment/spec.md`, task 7.6).

Answer 90: checked, no test-only setting or branch of this change is in real logic or service configuration. `SANDBOX_RUNTIME=runc` is the development runtime of Docker Desktop, not a test switch (D10), and the scripted spec's rules and overlay users live only in the e2e overlay and fixtures.

Answer 91.1: the deterministic spec of task 9.5 runs in the deterministic phase of `close-agent-test-gaps` D7, where the agent's semantic memory points at the AscendMemory fake under `/ascend-memory/` of `e2e-scripted-model`. AscendMemory is never restarted, there is no dummy key, and the spec wipes no memories (task 9.5). Answer 91.2: this change uses no fake MCP server.

Answer 91.3: the deterministic spec of task 9.5 is the one end-to-end spec of this change, because it proves the live path agent, runner, workspace, archive and cleanup that no lower test proves. Removed: the runner suite `apps/ascend-sandbox-runner/e2e/` with its probe image `ascend-e2e-bru:local`, its two specs and its allowlist entries (tasks 11.3, 11.4 and 11.5), because the runner integration tests of tasks 3.4 to 3.7 and 4.3 and the Pact test of task 8.2 prove the same refusals and lifecycle, and the output endpoint refusal spec (tasks 11.1 and 11.2), because the controller tests of task 8.8 prove its three 404 answers. The spec of task 9.5 now checks the runner's cleanup with `docker ps -a` and `docker network ls` filtered on the run's label instead of the probe.

Answer 93: the system task `sandbox-destroy-retry` is removed, because the runner's own expiry already removes the container, and the idle sweep closes the record afterwards (D11). With the retention moved to the shared retention task, the three agent side tasks are now one (D11, D12, tasks 8.7 and 8.8). The tenant header of the runner API is `X-Ascend-Tenant`, the one tenant header name of the platform, instead of `X-Tenant-Id` (D3, D15, D17, received from `add-coding-agent-delegation`). Not applied, because each would cut a feature (R3) or a company plug-in point (R2): egress per workspace, the sandbox image builder of D17, per-tenant workspace limits.

Answer 98: every value of this change that has a default is a setting with an environment variable, the same default in code and a compose line `${VAR:-default}` on its service, listed with its name and default in D18, and its rows go into `docs/CONFIGURATION.md` (runner, egress proxy, gateway) and `apps/ascend-agent/docs/CONFIGURATION.md` (agent) in the same commit as the setting (tasks 2.2, 7.2, 7.8, 8.1, 8.15 and 10.13). Made external, beside the keys the plan already had: the workspace `/tmp` size, the command kill and wait margins, the egress proxy and gateway sizes, the allow list cap on both sides, the egress proxy listen port, the service and image limits of D17, the coding area volume name and timeouts, the agent's runner timeouts and run TTL margin, the output bucket, the idle sweep's cron and zone, the runner port (`SANDBOX_RUNNER_PORT`) and the runner's compose memory limit (`SANDBOX_RUNNER_MEMORY_LIMIT`). Kept as constants, with the reason in D18: the workspace users, the path format rules, the ports inside the gateway and integration images, the alias, label and name patterns, the engine API minimum and the codes and metric names. Not decided and written neutrally: the nginx temp tmpfs size, the coding area mode default, the host run base URL of the agent, the agent's `limits.*` defaults and `output.max-bytes`, and Smokescreen's listen port, read at implementation time. No test or measurement of this change uses LM Studio as a default. D16 names a local LM Studio only as the example of an operator's private upstream.

Answer 98.1: there is no test line in `compose.yaml` and no `e2e` profile. In the deterministic phase the test overlay reaches the running agent by copy and a restart, and the end step recreates the agent from its image, with the steps of `close-agent-test-gaps` D7 (task 9.5). The runner image gets `WORKDIR /app` like the agent image (task 7.1), so the runner's configuration folder is `/app/config`, which the deterministic copy steps of `add-coding-agent-delegation` and `add-self-built-integrations` use. This change copies nothing into the runner itself.

Answer 98.9: one sandbox runner runs per Docker host and is shared by every agent copy on that host. The workspace row records its runner in the new column `sandbox_workspace.runner_base_url`, and every later call for a workspace goes to the runner its row names (D8, D11, D12, tasks 3.8, 8.3 and 8.14, specs `agent-sandbox-runner` and `agent-sandbox-tools`). This settles the open point of answer 87 whether the runner runs as several instances.

Answer 99.1: the group 5 change `plan-scaled-deployment` (a Kubernetes Helm chart with a Horizontal Pod Autoscaler for company deployments) is created after this round. Where this change says how agent copies on several Docker hosts are deployed, it names it in the form of the mandatory owner rule: company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it (D11). This change plans no host port range for several copies (answer 98.6).

## Owner decisions of 2026-10-09

Answer 100.6: every published host port is a setting `${<SERVICE>_HOST_PORT:-<today's port>}:<container port>`. The copied `production-deployment` requirement "Internal service ports bind to loopback by default" now names the form `"${EXPOSE_BIND:-127.0.0.1}:${<SERVICE>_HOST_PORT:-<host-port>}:<container-port>"` of `harden-cloud-deployment`. `ascend-sandbox-runner` and the gateways of this change still publish no host port, so no setting is added.

Answer 99.1: the Kubernetes Non-Goal now names `plan-scaled-deployment` (company, build group 5, position 9), which plans the runner as one copy per node (a DaemonSet) whose address each agent copy of that node uses, so the base URL a workspace records still names its runner. This change does not wait for it and changes no task.

## Open Questions

None. The owner decided on 2026-10-02 that the personal deployment's default tool policy allows the three sandbox tools, that disk-backed workspaces belong to `add-coding-agent-delegation` and use its shared coding project area, that rootless Docker under gVisor is a non-goal for now, that sandbox time is its own metered operation type and a runner metric, and that the default limits in D4 are 1 CPU, 1 GiB memory, 512 MiB workspace and 30 minutes per workspace, with 4 workspaces at once in total for a 24 to 32 GB server. In answer 21.6 he decided that the main chat also gets `shell`, `file_read` and `file_write`, always inside a sandbox workspace of its own per conversation, and that Ascend's own services do not run under gVisor. The lifetime of a chat workspace (idle close after 30 minutes, at most 2 hours, at most 2 open per tenant, `out` saved on close) is this design's choice in D11 and is configuration. In answer 44 he approved `CODING_AREA_HOST_PATH` and a separate partition at `/srv/ascend/coding` for the coding project area (D15), and in answer 46.2 that the runner holds integration secrets from the separate file `integration-secrets.env` (D9). On 2026-10-03 he decided that the sandbox is core, always on and never switchable, while tenant policy can still switch the shell tools off per tenant (D9, D11).
