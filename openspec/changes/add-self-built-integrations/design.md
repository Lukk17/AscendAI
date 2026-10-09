## Context

See proposal.md for why. This section holds only the current state that shapes the approach.

- `add-coding-agent-delegation` runs OpenCode headless in a disk-backed gVisor workspace of the sandbox runner, the only coding agent it has (its owner decision 36.1). Secrets never enter the workspace: a per-workspace credential gateway (nginx, routes rendered from JSON, secret values written through exec standard input into a tmpfs) adds the model key and the git token. A run is a row of `subagent_run` of kind `coding` with a detail row in `coding_run`. Its result (summary, diff, commits, a git bundle) goes to the bucket `coding-output`. Its sources are a GitHub repository, a new empty project, or a seed folder given by trusted agent code (its D3), and its tool `delegate_coding` is offered to the main chat.
- `add-agent-sandbox` gives the runner on port 9940, the only holder of the Docker socket, with workspaces on `runsc`, no network or an internal network whose only exit is a per-workspace Smokescreen proxy, image profiles pinned by digest, labels on every object and a reaper. At most 4 workspaces exist at once. The runner never sets `Binds`, `Privileged`, `CapAdd` or host networking.
- `add-mcp-tool-servers` reads every configured MCP server from one entry under `app.mcp.servers.<id>` at startup, accepts run-time entries from an `McpServerEntrySource` with a tenant scope and a metric tag (its D10), derives the Spring AI connection list from it, connects only over Streamable HTTP, prefixes every tool name, sends tools of `discovery: search` servers only through tool search over the capability index type `tool`, gives each tool a default mode, has a failed server retried in the background by `McpReconnectScheduler` of `add-deployment-modules`, and has no user interface for server configuration.
- `add-action-approvals` reserves the kinds `integration_credential` (always remembered as an allow on approve, scope `integration=<id>, credential=<name>, binding=<binding_sha256>`) and `integration_egress` (always remembered as an allow on approve, scope `integration=<id>, host=<host>`) for this change, which registers their handlers, and the rule-only kind `integration_tool_review` (category `tool_review`, scope `integration=<id>, tool=<name>, definition=<definition_sha256>`), whose rules this change writes through `ApprovalService.putRule` (owner answer 89.4 of 2026-10-08). `approval_request` is the only record of an approval and `approval_rule` the only record of a remembered decision. Its `ToolCallApprovalHandler` re-reads a gated tool through `ChatToolset` at execution and refuses `tool_changed` when the definition digest differs.
- `add-agent-skills` gives `app.agent-home` with the tenant folder `tenants/<tenantId>/`, one git repository per concern in it through the generic `VersionedFolder` on JGit, and the capability index with tenant-keyed and global entries.
- The secrets of the stack live in the root `.env` and reach each service through compose. The sandbox runner already writes secret values into a gateway's tmpfs for coding runs.
- `add-deployment-modules` switches whole features with `COMPOSE_PROFILES`, read by the agent as `ASCEND_MODULES`, and `@ConditionalOnModule` on every bean of a module. Its catalog has the module `self-built-integrations`, which requires `coding` and uses `self-improvement` (D26). The sandbox runner is core and always on (owner decision of 2026-10-03), so neither `coding` nor this module requires a sandbox module.
- `add-keycloak-login` (build group 3, position 3, split out of `add-auth-and-identity` on 2026-10-04) lands before this change. It gives the tenant seam `TenantContext.currentTenantId()` with `TenantContext.runAs(tenantId, action)` (its D3 and task 3.9), which answers `default` in the personal deployment and throws when nothing is bound (fail closed), the realm roles `USER` and `ADMIN` and one authorization matrix in `SecurityConfig`, and a change that adds endpoints after it adds its own rows to that matrix with a security slice test per row (D13), which its coverage test `SecurityMatrixCoverageTest` enforces.
- `add-tenant-isolation` is company work of build group 5 and lands later. It creates the `tenants` table and adds the foreign keys from the `tenant_id` columns of this change's tables to `tenants(id)` in its own migration (D17). This change does not wait for it.
- `add-agent-subagents` filters every tool through the tool policy port `TenantToolPolicy`, whose default allows every tool. `add-tenant-policy` (company, build group 5) registers its tenant allow-list implementation later, where a new tool ships off. `add-mcp-tool-servers` adds `server:<id>` entries and a deny list.
- `add-deployment-modules` owns the company extension ports `AuditEventPort` (default `LogAuditEventPort`, one structured INFO line), `UsageEventPort` (default `NoOpUsageEventPort`), `QuotaGate` (default `AllowAllQuotaGate`) and `ModelAccessPolicy` (default `ConfiguredModelAccessPolicy`, every provider the deployment has enabled). `add-audit-and-gdpr-compliance` and `add-usage-metering-and-quotas` register their implementations later.
- `add-shared-scheduler` runs each system task on exactly one agent instance per firing, and its D2 keeps work that only refreshes one instance's memory local.
- `add-self-improvement` (build group 4, position 13 of the owner build order of 2026-10-04, so it lands before this change) records every self change with a report and an undo, offers `SelfChangeRecorder.recordIntegrationEvent(...)` and the `SelfChangeUndoHandler` port for integration events (its D11 and D13), and its review runs with no tool that reads outside content.
- Production target: one virtual server per customer, 24 to 32 GB of memory, no nested virtualization. Development: Docker Desktop on Windows 11 with `runc` and WARN banners.

### Measured and sourced facts this design rests on

Checked on 2026-10-02:

| Fact | Source |
| :--- | :--- |
| Rootless BuildKit in a container needs `seccomp=unconfined`, `apparmor=unconfined` and `systempaths=unconfined`, or `--privileged`, which its docs call "almost safe for rootless" | https://github.com/moby/buildkit/blob/master/docs/rootless.md |
| `--oci-worker-no-process-sandbox` avoids `systempaths=unconfined` but "allows ExecOp containers to kill (and potentially ptrace ...) an arbitrary process in the BuildKit daemon container" and cannot end stuck build steps | same page |
| BuildKit is Apache 2.0, latest release v0.33.1 on 2026-09-30 | `gh api repos/moby/buildkit/releases/latest` |
| `GoogleContainerTools/kaniko` is archived, last push 2025-06-03 | `gh api repos/GoogleContainerTools/kaniko` |
| The maintained fork `chainguard-dev/kaniko` (Apache 2.0, last push 2026-09-28) says kaniko "does not make it safe to run untrusted builds", "unpacks directly into its own container root", and is supported only in its own image | https://github.com/chainguard-dev/kaniko |
| Engine API `PUT /containers/{id}/archive` extracts a tar into a container path, `POST /commit` creates an image from a container with optional `changes` and a `ContainerConfig` body | `api/swagger.yaml` of `moby/moby` master, API version 1.56 |
| `docker cp` works on "a running or stopped container", container paths are relative to the container root, and copied files are owned by root unless ownership is kept on purpose | https://docs.docker.com/reference/cli/docker/container/cp/ |
| Smokescreen ends on `SIGHUP` (it is in the same signal set as `SIGTERM`), so its ACL cannot be reloaded in place | `pkg/smokescreen/smokescreen.go` of `stripe/smokescreen`, `signal.Notify(kill, syscall.SIGUSR2, syscall.SIGTERM, syscall.SIGHUP)` |
| FastMCP is Apache 2.0 under `PrefectHQ/fastmcp`, latest release v4.0.10 on 2026-09-25. ascend-ocr pins 3.3.1 today. After `add-python-runtime-upgrades` (build group 2, position 2 of the owner build order of 2026-10-04) every Python service pins FastMCP 4.0.10 through the `ascend-python-common` library | `gh api repos/PrefectHQ/fastmcp`, `apps/ascend-ocr/pyproject.toml`, `add-python-runtime-upgrades` design D1 |
| docker-java latest 3.7.1 on 2026-03-18, the runner's engine client | `gh api repos/docker-java/docker-java/releases/latest` |

## Goals / Non-Goals

Goals:

- The assistant can go from "I need a connection to X" to a running, tested, isolated MCP server without the owner, and without writing the code itself.
- Code the assistant caused to be written is treated as untrusted: it runs under gVisor, reaches nothing but its approved hosts, holds no secret, and cannot reach the agent.
- The two owner gates of 2026-10-02 hold by construction: no credential without an `integration_credential` approval, and no outside send without an `integration_egress` approval for that host.
- Reuse the runner, the coding run, the MCP server entries, the approval service and the credential gateway of the sibling changes, and add only what an integration needs.

Non-Goals:

- Integrations in other languages than Python. The template is one language, so the checks, the runtime image and the contract checker are written once.
- OAuth flows with a browser consent, refresh tokens, request signing (for example AWS SigV4 or HMAC) and API keys in a query string. The gateway adds a fixed header only. An outside system that needs more is refused at build time with `credential_kind_unsupported`, and the owner can connect it as a configured MCP server of `add-mcp-tool-servers` instead.
- Inbound traffic to an integration from the internet (webhooks). Integrations are called by the agent only.
- Integrations shared between tenants, or published to a registry or a git host.
- A static code review of the generated source as a security boundary. The boundary is the sandbox, the network and the gateway. The checks of D6 make the integration correct, not safe.
- A user interface. The owner uses the REST API now and the app later.
- Data migration. The project is under development, so there is nothing to migrate. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

## Decisions

### D1: The flow from need to running integration

One background run of kind `integration`, a run kind that `add-agent-subagents` owns, drives a build in stages. Each stage is the run's last step text and a field of the version record:

1. Request: `integration_build` or `integration_update` validates the input (spec `integration-build`), writes the integration row (first build) and a version row in `building`, and starts the run.
2. Seed: the agent writes a seed folder: the template of `infra/integrations/template/` with the slug filled in, `BUILD_REQUEST.md` with the request, and for an update the integration's current folder from the tenant repository.
3. Code: an OpenCode coding run of `add-coding-agent-delegation` with source `seed` (D4), started by trusted agent code with no integration-specific cost or time limit (D15), child of the integration run.
4. Accept: the agent reads the coding run's bundle from `coding-output`, fetches it into the tenant's integration repository with JGit in a temporary branch, checks the changed paths and the manifest (D2, D3), and on success fast-forwards the integration's branch, which is one commit per version.
5. Dependencies: a fresh workspace of profile `integration-verify` with the package index allow-list installs `requirements.lock` into `/workspace/out/deps` (D5).
6. Verify: a fresh workspace of profile `integration-verify` with no network gets the source archive and the dependency archive, runs the tests and the contract check (D6).
7. Image: the agent sends the same two archives, compared by SHA-256, to `POST /v1/images` of the runner (D7).
8. Run: the agent asks the runner to start or replace the integration service (D8, D9), registers the MCP entry when it is healthy (D10), and submits the egress and credential approvals that are still needed (D11, D12).

A failure at any stage ends the run `failed` with one of the reasons `CODING_AGENT_ERROR`, `SANDBOX_ERROR`, `INTEGRATION_VERIFY_FAILED` or `INTEGRATION_IMAGE_FAILED` and a detail code, marks the version `rejected` or `failed`, destroys every workspace of the run, and leaves the previous active version untouched. A cancel of the run cancels the coding run and destroys the workspaces.

The integration run uses its own pool of the one slot pool `RunSlots` of `add-agent-subagents` (its D10, answer 89.7 of 2026-10-08), not the subagent worker slots, because a build holds a coding run for as long as the coding agent works. This change registers the pool `integration` for the run kind `integration` with one `RunPoolRegistration` bean: the running limit is the safety bound `max-running-builds` (default 1) and the waiting bound is unbounded, so builds wait in arrival order with no count limit (owner decision 40.4). It keeps no slot pool of its own. The counts live in the `subagent_run` rows in Postgres, so the bound holds across every agent instance (answer 87). The coding run inside a build uses the pool `coding` of `add-coding-agent-delegation`, so a build waits there like any other coding run.

One build per integration at a time holds across agent instances too (answer 87): the version row of a build is inserted in `building` under the partial unique index `integration_version_one_building_uk` on `(tenant_id, integration_id) WHERE state = 'building'`, so a second build of the same integration started on another instance fails that insert and answers the model that a build is still running.

Alternatives considered: the model calls `delegate_coding` and then a separate `integration_register` tool with the result (rejected: the model would carry the source between steps, could change it, and could skip the checks), and building inside the coding workspace with the coding agent's own tests (rejected: the coding agent controls that workspace and could fake a green test run).

### D2: The manifest and the fixed template

`infra/integrations/template/` holds:

- `integration.yaml`: `slug`, `title`, `version`, `destinations` (`host`, `purpose`), `credentials` (`name`, `kind`, `header`, `host`, `path-prefixes`, `purpose`), `tools` (`name`, `effect`, `description`). The coding agent fills it from the build request, and D3 checks it against the request.
- `app/server.py`: a FastMCP server skeleton that exports `mcp`. Tools call outside hosts only through `app/outside.py`.
- `app/outside.py`: fixed helper with two functions, `client()` (an HTTPX client that goes through `HTTPS_PROXY`) and `credential_client(name)` (an HTTPX client whose base URL is the gateway route `http://gateway:8080/cred/<name>`). It is in the allowed path list but its content is compared with the template, so the coding agent cannot change it.
- `tests/`: a pytest example with a fake outside system through `respx`, and `conftest.py` that blocks real sockets.
- `requirements.lock`: empty by default.
- `README.md` for the coding agent: the rules (no other files outside the allowed paths, never read environment variables for secrets, use only `outside.py`, one test per tool at least, keep the manifest equal to the request, never call a declared destination from tests).

Allowed paths per integration folder: `integration.yaml`, `README.md`, `requirements.lock`, `app/**/*.py`, `tests/**/*.py`, `tests/fixtures/**/*.json`. Everything else is refused.

The runtime image `infra/integrations/images/runtime/` starts from a pinned `python:3.12-slim` digest, installs pinned `fastmcp` (the version current when task 4.1 runs, which `add-python-runtime-upgrades` does not constrain, because the runtime image does not use the library's 4.0.10 pin), `httpx`, `pydantic` and `uvicorn`, writes their names to `/opt/ascend/runtime-packages.txt`, adds the fixed entrypoint `ascend_integration_runtime` (loads `app.server:mcp`, serves Streamable HTTP at `/mcp` on port 8000, serves `/health`, adds `/app/deps` to the path, refuses to start when `integration.yaml` lists a tool the server does not), creates user 10003, removes set-user-id bits, and runs as 10003. The verify image adds `pytest`, `respx`, `pytest-socket` and the contract checker `ascend-integration-check` on top of the same runtime layers, so tests run on the exact interpreter and libraries of production.

Why Python with FastMCP: the repository's Python services already use FastMCP for their MCP surface (`AGENTS.md` cross-module conventions), the image stays small, and coding agents write it well. Why a fixed helper for outside calls: it makes the credential path the same for every integration, so the gateway (D9) is the only place a secret is added.

### D3: The source repository per tenant and the accept step

The repository is `<app.agent-home>/tenants/<tenantId>/integrations/`, a `VersionedFolder` of `add-agent-skills` next to `skills/` and `.claude/agents/` (required edit there for the layout statement). One folder per integration, named by its slug, one commit per accepted version with the trailers `Integration-Id`, `Integration-Version`, `Integration-Run` and `Coding-Run`.

The accept step reads the coding run's `changes.bundle` and fetches it with JGit's bundle transport into `refs/candidates/<run id>`, then checks, before any ref of the repository moves:

- every changed path is under `<slug>/` and matches the allowed paths of D2,
- no entry is a symbolic link, a submodule or an executable bit file,
- the size safety bounds (`max-file-bytes` 1 MiB, `max-source-bytes` 5 MiB, D15),
- `app/outside.py` equals the template's,
- the manifest parses, has the request's slug, and its destinations, credentials and tools equal the request's (for an update: the request's change applied to the current manifest).

On success the candidate commit is squashed into one commit on `main` with the trailers. On failure the candidate ref is deleted and the version is `rejected` with `manifest_mismatch` or `source_refused`. The coding run's result in the object store keeps its own retention.

### D4: The coding run, started from a seed

Edit to `add-coding-agent-delegation`, made in that change (its D3, D6, D8, D14, D15 and D21 and its `coding-delegation` spec): a trusted internal entry point (not a tool, `CodingRunService.startSeeded` of its D3) starts a coding run with source `seed`: the agent passes a tar of the seed folder, the runner writes it into `/workspace/repo` with `PUT .../files` and the orchestrator commits it as the base commit, so the diff and the bundle are relative to the seed. A run with source `seed` has no `git` route in its gateway, only the `model` route, uses the egress allow-list given by the caller (here `app.integrations.build.network.allow`, default `pypi.org` and `files.pythonhosted.org`), has `purpose` `integration`, and refuses `coding_publish` with `coding_not_publishable`, the code that change owns for a `new_project` or `seed` project. The project carries `source_kind` (`github`, `new_project`, `seed`) and `purpose` (its D3 and D15).

The coding agent is OpenCode, the only coding agent of `add-coding-agent-delegation`, so this change has no setting to choose one. The provider, the model and the key are resolved and checked the same way as for any coding run: the provider and model through the `ModelAccessPolicy` port of `add-deployment-modules` (its default allows every provider the deployment has enabled, and `add-tenant-policy` registers the tenant rules later), and the key through `ProviderKeyResolver` of `add-coding-agent-delegation` (its default returns the deployment key, and `add-usage-metering-and-quotas` registers the per-tenant key later).

### D5: Dependencies without running package code

The dependency stage runs in a workspace of profile `integration-verify` with the allow-list of D4:

```
python -m pip install --no-deps --only-binary=:all: --require-hashes --target /workspace/out/deps -r /workspace/src/<slug>/requirements.lock
```

The agent first checks the lock: every line `name==version` with one or more `--hash=sha256:`, no URL, no path, no `-e`, no option lines other than `--hash`, no package listed in `/opt/ascend/runtime-packages.txt`. `--only-binary=:all:` makes pip refuse source distributions, so no `setup.py` or build backend of any package runs. The size of `/workspace/out/deps` is checked against the safety bound `max-dependency-bytes`. An empty lock skips the stage and the dependency archive is empty.

### D6: Tests and the contract check

The verify stage runs in a workspace of profile `integration-verify` with `network: none`. The agent uploads the source archive (the integration folder at the accepted commit) and the dependency archive, then runs, each as one runner command within the 900 second command maximum:

1. `python -m pytest -q -p no:cacheprovider --junitxml=/workspace/out/junit.xml` with `PYTHONPATH` set to the source and the dependencies. The agent reads the junit file and requires zero failures and errors, and at least one passed test whose name holds each declared tool name.
2. `ascend-integration-check --manifest integration.yaml --start "python -m ascend_integration_runtime"`, the fixed checker of the verify image. It starts the server on loopback, waits for `/health`, uses the MCP Python client over Streamable HTTP, and runs the checks of the spec. It prints one JSON report, which the agent parses.

The test and checker output is kept at most `app.integrations.safety.build.max-output-bytes` (default 64 KiB) and stored with the version under the object key prefix `tenant/<tenantId>/integration-builds/<integration id>/<version>/` in the bucket `coding-output`.

### D7: Image assembly without a build tool

Options compared for "build the image safely from the workspace output, with no Docker socket for the agent":

| Option | What runs during the build | Runs where | Needs | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| Rootless BuildKit (`moby/buildkit:rootless`) as a runner-started container | Every `RUN` step of a Dockerfile | A container that needs `seccomp`, `apparmor` and `systempaths` unconfined, or `--privileged`, or the discouraged no-process-sandbox mode | A new long-running or per-build container, a way to get the result into the engine | Rejected: it loosens exactly the settings the runner's forbidden-settings test refuses, gVisor support is not documented and not measured, and it exists to run build steps we do not need |
| kaniko (`chainguard-dev/kaniko`, Google's original archived 2025-06-03) | Every `RUN` step, unpacked over its own root | Its own image only, as root inside it | A registry or tar output | Rejected: archived upstream, "does not make it safe to run untrusted builds", and needs root in its container |
| Daemon BuildKit or the classic builder through the Engine API `/build` | `RUN` steps | The engine itself, outside any sandbox | The socket, which only the runner holds | Rejected for `RUN` steps. A Dockerfile with only `FROM` and `COPY` would be safe, but docker-java drives only the classic builder, which is deprecated |
| Jib Core in the runner | Nothing | Inside the runner JVM | A base image as a tar or from a registry, then `docker load` | Not chosen: a new dependency and a second image path, for the same result as the next row |
| Engine-native assembly: create a container from the runtime image without starting it, `PUT /containers/{id}/archive` for the two archives, `POST /commit` with fixed settings | Nothing | The engine, driven by the runner | Only the Engine API calls the runner already uses | Chosen |

Why it is safe: no code runs at build time at all, because the container is never started and an archive extraction and a commit execute nothing. All code execution (dependency install, tests, the server start of the contract check) happened earlier inside gVisor workspaces with no secrets. The image therefore holds exactly the bytes that were tested.

`POST /v1/images` (required edit to `add-agent-sandbox`), multipart with `profile` (`integration-runtime`), the `X-Ascend-Tenant` header, `integrationId`, `version`, `source` (tar) and `deps` (tar):

1. The runner validates each archive while streaming it to its tmpfs with Apache Commons Compress: only regular files and directories, relative paths with no `..`, no absolute path, no NUL, at most 1024 bytes per path, no set-user-id or set-group-id bit, at most `max-entries` (default 5000) and `max-bytes` (default 60 MiB together). It computes and returns each SHA-256, and the agent compares them with the tested archives before the image is used.
2. Creates a container from the profile's pinned image with `NetworkMode: none`, no command change and the image labels, and never starts it.
3. Extracts `source` into `/app/src` and `deps` into `/app/deps` with `noOverwriteDirNonDir=true`. Files are owned by root, so user 10003 can read and never change them.
4. Commits with `repo` `ascend-integration/<tenant>-<integration id first 12 hex>`, `tag` `v<version>`, `pause=false`, and a `ContainerConfig` that fixes `User` `10003`, `Cmd`, `Env` (`PYTHONPATH` only) and the labels `ascend.sandbox=true`, `ascend.sandbox.kind=image`, tenant, integration and version.
5. Removes the container and answers 201 with the image id, size and the two digests.

`DELETE /v1/images/{imageId}` removes an image after the tenant label check. The runner keeps at most `max-images-per-integration` (default 2) and the agent deletes older ones when a version becomes `superseded` twice.

Task 2.3 measures the five steps on Docker Desktop and on a Linux engine with the containerd image store, and records whether `commit` keeps the base layers shared.

### D8: The integration service and its safety bounds

`/v1/services` (required edit to `add-agent-sandbox`) manages long-lived integration services:

| Method and path | Body | Answer |
| :--- | :--- | :--- |
| `PUT /v1/services/{id}` | `imageId`, `limits`, `egress.allow` (hosts), `gateway.routes` (each credential route names its credential, never a value, D11), `ingressAlias` | 200 service view, creates or replaces so the observed state equals the body |
| `GET /v1/services` | | the calling tenant's services |
| `GET /v1/services/{id}` | | view with `state`, `health`, `restartCount`, `specDigest`, `startedAt` and `secretPresent` per credential route |
| `DELETE /v1/services/{id}` | | 204, removes container, gateway, proxy and network |

A service is the container of the integration, its network `ascend-int-<id>` (`internal: true`), its proxy and its gateway. The runner compares the SHA-256 of the canonical body plus a digest of each secret value it read from its environment with the label `ascend.sandbox.spec-digest`, and recreates only the parts that changed: a new image replaces the integration container, a new egress list replaces the proxy (Smokescreen cannot reload, it ends on `SIGHUP`), a new route or a changed secret value (after a runner recreate) rewrites the gateway's secret files and reloads nginx.

Integration container settings follow the workspace settings of the sandbox change (non-root 10003, `CapDrop: ALL`, `no-new-privileges`, read-only root, `runsc` in production, no `Binds`, no `Mounts`, `Dns` to an address that does not answer), plus `/tmp` tmpfs 32 MiB, `RestartPolicy: on-failure` with at most 3 tries, the image's health check, and the limits:

| Item | CPU | Memory | Processes |
| :--- | :--- | :--- | :--- |
| Integration container (safety bound default, maximum) | 0.25, 1.0 | 256 MiB, 1024 MiB | 128, 512 |
| Its egress proxy | 0.1 | 64 MiB | 64 |
| Its credential gateway | 0.1 | 64 MiB | 64 |

One running integration at the defaults reserves 384 MiB of memory and 0.45 CPU with its proxy and gateway, beside the 4 sandbox workspaces of about 7.5 GiB in the worst case of the coding change's D17. There is no count limit on services (owner decision 40.4), and services do not count against `max-workspaces`. The runner reports the reserved memory of all services as `sandbox.services.reserved.memory`.

Reaper rules for services (required edit): a service container has no expiry label and is never removed by the reaper. A proxy, gateway or network whose service container is gone is removed as `orphan`. An image with `kind=image` whose integration has no service and is older than one day and is not named by the agent's reconcile list is removed as `orphan_image`.

### D9: Networks: egress proxy, credential gateway and the ingress path

```
            integrations-ingress (internal, compose)
 ascend-agent ─────────────┬───────────────────────────
                           │ :8081 /mcp  (alias int-<id12>)
                    ┌──────┴───────┐
                    │  gateway     │── sandbox-egress ──► https://<credential host>
                    └──────┬───────┘
                           │ :8080 /cred/<name>/...
  ascend-int-<id> (internal, one per integration)
                    ┌──────┴───────┐        ┌──────────────┐
                    │ integration  │──────► │ egress proxy │── sandbox-egress ──► approved hosts
                    └──────────────┘ proxy  └──────────────┘
```

- The integration container joins only `ascend-int-<id>`. Its environment holds `HTTPS_PROXY` and `HTTP_PROXY` pointing at the proxy's address and `NO_PROXY=gateway`.
- The egress proxy is the Smokescreen image of `add-agent-sandbox` in `enforce` mode with `ALLOWED_HOSTS` equal to the approved destinations, on `ascend-int-<id>` and `sandbox-egress`. An empty list allows nothing.
- The gateway is the per-workspace credential gateway image of `add-agent-sandbox` D16 (`infra/sandbox/credential-gateway/`), with the route kind `inbound` that edit 8 of this change asked for and that is made there in its D16: it listens on port 8081 and forwards `/mcp` and `/health` to `http://integration:8000`, without adding any header. Its credential routes listen on port 8080 and follow `add-agent-sandbox` D16 and `add-coding-agent-delegation` D7 unchanged (fixed upstream, allowed path prefixes, one header, rate per minute, secret files on a tmpfs, nothing logged but the access line). A credential route's upstream host must be an approved destination of the integration, checked by the agent before every `PUT /v1/services/{id}`. The gateway joins `ascend-int-<id>`, `sandbox-egress` and `integrations-ingress`, with the alias `int-<id first 12 hex>` on the last one.
- `integrations-ingress` is declared in `compose.yaml` with `internal: true`, and the agent joins it. Only the agent and gateways are on it. A gateway forwards only to its own integration and to its fixed upstreams, so neither an integration nor a gateway can reach the agent's port through it.

Why the agent does not join each integration network: it would put the agent's port 9917 next to generated code, and the approval change's D12 relies on untrusted code never reaching the decision endpoints. Why not one shared integrations network for the containers: integrations could reach each other.

### D10: Registration as an MCP server entry

`add-mcp-tool-servers` D10 provides run-time entries: server entries come from `McpServerEntrySource` beans, the configuration source keeps the startup path of its D1 unchanged, and `IntegrationMcpEntrySource` of this change adds and removes entries at run time through its `McpServerRegistry`. That change builds the `McpSyncClient` of a run-time entry itself with the same customizers (no service token and no `_meta`, because the trust is `external`), keeps it in its `RuntimeMcpClientRegistry`, publishes `McpToolsChangedEvent`, and covers run-time entries with its background retry. `McpClientAutoConfiguration` is not replaced, so `mcp-startup-resilience` holds.

An integration entry:

| Field | Value |
| :--- | :--- |
| id | `int-<slug>`, unique within the tenant |
| tenant | the integration's tenant. Tools are offered only to that tenant's requests, and the tool entries in the capability index are tenant-keyed with key `<tenant>//<prefixed name>` |
| module | `self-built-integrations`, so switching the module off removes every integration entry |
| metric-server-tag | `integration` |
| url | `http://int-<id12>:8081`, endpoint `/mcp` |
| trust | `external` |
| tool-prefix | the slug, which cannot equal a configured prefix (checked at build) |
| discovery | `search` |
| default-mode | `requires_approval` |
| overrides | from the owner's tool reviews (D13), which are remembered rules of kind `integration_tool_review` of `add-action-approvals`, and per tool `category` from the manifest effect (`read` and `write` to `other`, `message` to `outside_message`, `money` to `spend_money`, `delete` to `outside_delete`), `rememberable` false |
| metered | `true` |
| request-timeout | the safety bound `app.integrations.safety.call-timeout` (default 30 seconds) |
| max-result-chars | `app.integrations.max-result-chars` (default 20000) |

Through `metric-server-tag`, the tags `server` and `tool` of `mcp.tool.duration` are `integration` for every integration entry, so the tags stay bounded. Tool names become `<slug>_<tool>`.

The tool modes and their approval metadata reach `add-action-approvals` through the `ApprovalDefaultsSource` that the MCP change already adds, now fed by both sources. Because a review is a rule scoped to the tool's definition digest, a new version that changes a tool makes it `requires_approval` again, and an approval waiting from the old version fails with `tool_changed` by the approval change's own rule.

### D11: Credentials

Owner decision 40.1 of 2026-10-02: integration passwords and tokens are environment variables given through docker compose, not rows in a database table.

- Variable name: each declared credential is referenced by one environment variable whose name the runner derives, so neither the model nor the agent can choose it: `INTEGRATION_SECRET_<first 12 hex characters of the integration id, upper case>_<credential name, upper case>`, for example `INTEGRATION_SECRET_3F9A0C1B22D4_API_KEY`. The integration id ties the name to one integration of one tenant. A credential of kind `basic` uses two variables with the suffixes `_USERNAME` and `_PASSWORD`. The integration view and the approval preview show the name.
- Which service holds the values: the sandbox runner, because it is the component that writes a secret into a gateway's memory-backed folder (D9) and already does so for coding runs. The agent never holds an integration secret, so a prompt injection or a bug in the agent can never reveal one. Compose passes the values to the runner only, through `env_file: [{ path: integration-secrets.env, required: false }]` on `ascend-sandbox-runner`. The file sits next to `compose.yaml`, is ignored by git, and is documented by `integration-secrets.env.example`. The root `.env` is not used for these values, because loading it with `env_file` would hand every other secret of the stack (provider keys, database password) to the runner, and naming each variable in `environment:` would need a compose edit per credential.
- Request: `integration_request_credential` submits `IntegrationCredentialAction` (kind `integration_credential`) with payload: integration id, version, credential name, kind, header, host, path prefixes, the variable name, and the manifest digest. Preview built from the stored manifest, with the variable name and the fixed text that the owner adds the value to `integration-secrets.env` and never types it into a chat. The credential row does not record the request: the pending approval of kind `integration_credential` with the scope `integration=<id>, credential=<name>, binding=<binding_sha256>` is the request (owner answer 89.4 of 2026-10-08). A second request while one is pending returns the pending approval id, by the duplicate rule of the approval service, so two instances that receive the same request at once still leave one pending approval (answer 87).
- Handler `IntegrationCredentialApprovalHandler`: execute returns "granted, waiting for the value in the runner's secrets file" and reconciles the integration. The grant itself is the `allow` rule that the approval service always remembers on approve for this kind, scoped to the integration, the credential name and the binding digest. Deny and expiry move the integration to `blocked` when the credential is required by the active version.
- How a value arrives: the owner adds the line `<variable>=<value>` to `integration-secrets.env` and recreates the runner with `docker compose up -d ascend-sandbox-runner`. A running integration container is not touched by this: the runner adopts its services by their labels at startup (required edit to `add-agent-sandbox`), and the next reconcile writes the new value into the gateway. This restart is the accepted minus of the decision: a new or changed secret needs a recreate of the runner, and the runner API is unavailable for its few seconds of startup, so the owner does it when no build runs. A running coding or sandbox run sees one failed runner call and retries by the rules of its own change.
- Discord prompt: the approval prompt that `add-openclaw-plugin-host` posts on Discord for an `integration_credential` approval (its D12 `ApprovalChangedEvent` listener) carries one fixed line, added by this change to the prompt payload when it is built: the secret is added by the owner to the integration secrets file `integration-secrets.env`, which only the sandbox runner reads (owner answer 46.2), and is never typed into any chat. The prompt shows the variable name the approval names and never a value. This line moved here from `add-openclaw-plugin-host` task 5.4 (dependency fix of 2026-10-05). Its Approve and Deny buttons are the action types `approval_approve` and `approval_deny` of the one action endpoint `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host`, and this change adds no button path of its own (owner answer 89.6 of 2026-10-08).
- Delivery: the agent's `PUT /v1/services/{id}` body names, per credential route, only the variable name. The runner reads the value from its own environment at that moment, writes it into the gateway's tmpfs through exec standard input, and never returns, logs or labels it. The service view reports per route only `secretPresent: true|false`. A route whose variable is missing or empty is not created, and the integration stays `awaiting_owner` with the reason `credential_value_missing`, which the reconciler shows on the integration view and in the waiting tool result.
- Binding change: a new version whose credential keeps name, kind, header, host and path prefixes keeps the same binding digest, so the existing `allow` rule still grants it and the variable stays. Any change of those gives a new binding digest, which no rule covers, so a new `integration_credential` approval is needed for the new version, because a credential must reach only the host the owner approved it for.
- Revocation: `DELETE /api/v1/integrations/{id}/credentials/{name}` removes the grant rule through `ApprovalService.deleteRules(tenantId, "integration_credential", "integration=<id>, credential=<name>,")`, sets `revoked_at` on the credential row and reconciles that integration at once (D25), which removes the route from the gateway whatever the file still holds. The owner then deletes the line from `integration-secrets.env`. The integration view lists every variable of a removed or revoked credential that the runner still reports as present, so a stale line is visible.
- The credential state shown in the integration view is read, never stored: `granted` when an `allow` rule covers the current binding, `requested` when an approval of that scope is pending, `denied` or `expired` when the newest decided approval of that scope says so and no rule grants it, `revoked` when `revoked_at` is newer than the newest approval of that scope, otherwise `declared`. A decided approval older than the approval retention is gone, so its credential then reads `declared` again, which asks nothing new of the owner, because no rule grants it.

### D12: Egress approvals

- Registration and each version that adds a host: one `IntegrationEgressAction` (kind `integration_egress`) per host without a decided approval, scope `{integration id, host}`, preview with title, host, purpose and tools.
- Handler `IntegrationEgressApprovalHandler`: execute reconciles the integration. The approval service itself remembers the allow (its D9), and that rule is the record of the approved host. Deny and expiry move the integration to `blocked`.
- Source of truth: the approved hosts of an integration are the hosts with a remembered `allow` rule of kind `integration_egress` for its id. `integration_destination` rows hold only the host and its purpose. The state the view shows is read: `approved` when an `allow` rule of the scope exists, `pending` when an approval of the scope is pending, `denied` or `expired` from the newest decided approval of the scope, and `revoked` when an approval of the scope was approved and no `allow` rule exists any more. The reconcile of D25 reads the rules, so a rule removed through `DELETE /api/v1/approvals/rules/{id}` takes effect at the next run of `integration-reconcile`, and at once through `ApprovalRuleChangedEvent` (required edit to `add-action-approvals`: publish that event after commit when a rule is created, replaced or removed).
- Removal of an integration deletes its rules through `ApprovalService.deleteRules` of `add-action-approvals` (its D9), called with the integration's tenant and the scope prefix `integration=<id>,` once for each of the kinds `integration_egress`, `integration_credential` and `integration_tool_review`.

### D13: Owner management and the model's tools

States and moves are those of the `integration-management` spec. `IntegrationController` under `/api/v1/integrations`:

| Method and path | Who | Answer |
| :--- | :--- | :--- |
| `GET /api/v1/integrations` | tenant user | cursor page |
| `GET /api/v1/integrations/{id}` | tenant user | integration view |
| `GET /api/v1/integrations/{id}/versions` | tenant user | versions |
| `GET /api/v1/integrations/{id}/versions/{version}/report` | tenant user | test and checker report |
| `PUT /api/v1/integrations/{id}/tools/{tool}/review` | `ADMIN` | 200 with the review |
| `DELETE /api/v1/integrations/{id}/tools/{tool}/review` | `ADMIN` | 204 |
| `POST /api/v1/integrations/{id}/disable` | `ADMIN` | 200 |
| `POST /api/v1/integrations/{id}/enable` | `ADMIN` | 200 |
| `POST /api/v1/integrations/{id}/update` | `ADMIN` | 202 with the run id |
| `POST /api/v1/integrations/{id}/rollback` | `ADMIN` | 200 |
| `DELETE /api/v1/integrations/{id}` | `ADMIN` | 204 |
| `DELETE /api/v1/integrations/{id}/credentials/{name}` | `ADMIN` | 204 |

Views carry an `ETag` from the row version, and writes accept `If-Match`, the same pattern as the approval endpoints.

Tool reviews are remembered rules of kind `integration_tool_review` of `add-action-approvals` (owner answer 89.4 of 2026-10-08), not a table of this change. `PUT .../tools/{tool}/review` with mode `allowed` writes the rule through `ApprovalService.putRule` with the scope `integration=<id>, tool=<tool>, definition=<current definition digest>` and effect `allow`. `PUT` with mode `requires_approval` and `DELETE` remove the rules of that tool through `deleteRules` with the prefix `integration=<id>, tool=<tool>,`. The review in the integration view is read from these rules, which is the filtered approval view the owner asked for. A tool with no rule at its current digest is `requires_approval`, so an unreviewed tool and a tool reviewed as `requires_approval` behave the same.

Login roles: this change adds its own rows to the authorization matrix of `add-keycloak-login` in `SecurityConfig`, in the filter chain like every other row:

| Path | Rule |
| :--- | :--- |
| `GET /api/v1/integrations`, `GET /api/v1/integrations/**` | authenticated, scoped by the controller to the caller's tenant |
| `PUT` and `DELETE` on `/api/v1/integrations/*/tools/*/review`, `POST /api/v1/integrations/*/disable`, `POST /api/v1/integrations/*/enable`, `POST /api/v1/integrations/*/update`, `POST /api/v1/integrations/*/rollback`, `DELETE /api/v1/integrations/*`, `DELETE /api/v1/integrations/*/credentials/*` | `ADMIN` only |

The filter chain answers 403 to a `USER` token on an owner endpoint before the controller runs. The controller checks `ADMIN` of the integration's own tenant again, and an `ADMIN` of another tenant gets 404, because the row is not found under the caller's tenant. Under the Spring profile `dev` the synthetic identity holds both roles, as that change defines.

The model's tools: `integration_build`, `integration_update`, `integration_request_credential`, `integration_list` and `integration_disable`. They are main chat only, like `delegate_coding`, and none of them can enable, roll back, remove, review a tool or revoke a credential, and no tool or endpoint of any kind takes a credential value. Why the model may disable but not enable: disabling only removes capability, and an assistant that sees its own integration misbehave should be able to stop it. Enabling an integration that the failure rule stopped could loop.

Update: a new version runs D1 while the active version serves. When it is `ready`, the agent checks D11 and D12 for new hosts and changed credentials. With nothing new it replaces the service at once (`PUT /v1/services/{id}` with the new image), waits for health, re-registers the entry and marks the old version `superseded`. With something new the version waits in `awaiting_owner` and is activated by the handler of the last approval it waits for. Activation is a conditional update on the integration's `active_version`, so two finishing paths cannot both activate.

Rollback: the previous version's image becomes the service image, the two version states swap, and the tool review rules at the old digests apply again, because they were never removed.

### D14: Health and automatic disable

`IntegrationFailureTracker` listens to the outcome of every tool call of an integration entry (the `outcome` the MCP change already records) and to the reconciler's view of `health` and `restartCount`. Counts live on the integration row (`consecutive_failures`, `unhealthy_since`), updated with one statement per event, so a restart keeps them. A tool result with `isError: true` counts as a failure, because an integration that answers every call with an error is failing for the owner. Calls refused by the approval gate or by the waiting rule never count. At the limit the tracker moves the integration to `disabled_failing` with a conditional update and calls the same stop path as a disable.

Telling the owner: the finished runs block of `add-agent-subagents` lists the auto-disable once in the next chat turn of a conversation that used the integration, the audit event sent through `AuditEventPort` names it, and `add-self-improvement`, which lands before this change, records it as a change of operation `auto_disable` with the undo "enable" while the module `self-improvement` is active (D26). In the same transaction as the move to `disabled_failing`, the tracker creates one owner notification through `OwnerNotificationService.create` of `add-shared-scheduler` with source `integration`, kind `auto_disabled`, a fixed title of the source, a body that names the integration, its version and the reason with the failure count, and the integration id as its only subject id, addressed to each `ADMIN` of the integration's tenant through the offline `ADMIN` lookup of `add-keycloak-login`, the rule `add-self-improvement` uses for its reports. So the alert is stored, readable in `GET /api/v1/notifications` and the app's notification list, and delivered to every channel that reaches the user, Discord included (owner answer 89.6 of 2026-10-08: every alert is created through `OwnerNotificationService`).

### D15: No limits, only safety bounds

Owner decision 40.4 of 2026-10-02: no limits. There is no limit on the number of integrations per tenant, running integrations per deployment, builds per day, tools, destinations, credentials or dependencies, and no cost or time limit per build. The seeded coding run gets no integration-specific cost or time limit and runs under the run settings of `add-coding-agent-delegation` unchanged.

What stays are technical safety bounds that protect the server, each named as a safety bound under `app.integrations.safety`, each with a maximum the application checks at startup:

| Key | Default | Maximum | What it protects |
| :--- | :--- | :--- | :--- |
| `container.cpus`, `container.memory-mib`, `container.pids` | 0.25, 256, 128 | 1.0, 1024, 512 | one integration container cannot starve the host of CPU, memory or processes |
| `max-running-builds` | 1 | 2 | a build holds a coding workspace and two verify workspaces of the runner's at most 4 workspaces. Further builds wait in arrival order with no count limit |
| `build.max-file-bytes`, `build.max-source-bytes` | 1 MiB, 5 MiB | 4 MiB, 20 MiB | the repository and the image size |
| `build.max-dependency-bytes` | 50 MiB | 200 MiB | the disk of the verify workspace and the image size |
| `build.command-timeout` | 300 s | 900 s (the runner's command maximum) | a hung dependency install or test run cannot hold a workspace forever |
| `call-timeout` | 30 s | 120 s | a hung tool call cannot hold a chat turn |

The runner keeps its own safety bounds for archives (`max-entries` 5000, `max-bytes` 60 MiB) and its proxy and gateway sizes (D8).

There is no count of running integration services. The memory the integration containers reserve is visible as the sum of their memory limits in the banner and the runner metric `sandbox.services.reserved.memory`, and `docs/DEPLOYMENT.md` gives the sizing per container, so the owner sees growth before it matters.

### D16: Tenant scoping

The tenant comes from `TenantContext.currentTenantId()` of `add-keycloak-login` for the request that called the tool or the endpoint, never from tool input. In the personal deployment it answers `default`. Every store keys by tenant from the first day, so `add-tenant-isolation` (company, build group 5) only adds its foreign keys later and changes nothing here:

- Tables: every table of D17 carries `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()`, with no foreign key to a tenants table, and every repository query filters on `tenant_id`. A row of another tenant is answered as not found.
- Folders: the source repository is only `tenants/<tenantId>/integrations/` under `app.agent-home`.
- Objects: build reports only under the prefix `tenant/<tenantId>/integration-builds/` of the `coding-output` bucket, and the agent hands out a report only when its key starts with the caller's tenant prefix.
- Runner: every runner object carries the tenant label and the runner checks it, and the agent sends the tenant of the integration row as `X-Ascend-Tenant`. The secret variable name is derived by the runner from the integration id of a service whose tenant label it checks, so one tenant can never point a gateway at another tenant's secret.
- MCP and approvals: the MCP entry and its index entries are tenant-keyed, and the approvals are the tenant's.
- Fail closed: a tool call, an endpoint call or an approval handler with no bound tenant is refused, because `TenantContext.currentTenantId()` throws, and touches no row, folder, object or runner object. The system task `integration-reconcile` and the local entry refresh run without a request, so they bind the tenant of each integration row with `TenantContext.runAs(tenantId, action)` before any other step.

Tool policy: the five tools pass through the `TenantToolPolicy` port of `add-agent-subagents`, whose default allows every tool, so the personal deployment offers all five while the module is active. `add-tenant-policy` (company, build group 5) registers its implementation later, in which the five tools ship off for a new tenant and a new allow-list entry `integrations:own` allows every tool of the tenant's own integrations. The per tool mode still comes from the review. This change does not wait for it.

### D17: Tables and the Flyway migration

One Flyway versioned SQL migration `V<n>__create_integration.sql` (`<n>` the next free version at implementation time), every constraint and index named.

`integration`:

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` primary key | |
| `tenant_id` | `VARCHAR(64)` not null | From `TenantContext.currentTenantId()`, no foreign key in this change |
| `slug` | `VARCHAR(24)` not null | Unique with `tenant_id` |
| `title` | `VARCHAR(80)` not null | |
| `state` | `VARCHAR(20)` not null | Check in the seven states |
| `active_version`, `previous_version` | `INTEGER` null | |
| `disabled_by`, `disabled_reason` | `VARCHAR(8)`, `VARCHAR(500)` null | `owner`, `model`, `system` |
| `consecutive_failures` | `INTEGER` not null default 0 | |
| `unhealthy_since`, `last_failure_at` | `TIMESTAMPTZ` null | |
| `created_by` | `VARCHAR(255)` null | Set to null by user erasure |
| `created_at`, `updated_at` | `TIMESTAMPTZ` not null | |
| `version` | `BIGINT` not null | Optimistic lock and `ETag` |

`integration_version`: `tenant_id`, `integration_id` (FK `ON DELETE CASCADE`), `version`, primary key both, `state` (check in the seven version states), `manifest` `JSONB`, `manifest_sha256`, `commit_id` `CHAR(40)`, `build_run_id`, `coding_run_id` `UUID`, `source_sha256`, `deps_sha256` `CHAR(64)`, `image_id` `VARCHAR(80)`, `failure_reason` `VARCHAR(32)`, `failure_detail` `VARCHAR(500)`, `report_key` `VARCHAR(512)`, `cost_usd` `NUMERIC(12,6)`, `created_at`, `updated_at`.

`integration_destination`: `tenant_id`, `integration_id`, `host` (primary key `integration_id` and `host`), `purpose`. The decision on a host is the approval and its rule, never a column here (owner answer 89.4 of 2026-10-08).

`integration_credential`: `tenant_id`, `integration_id`, `name` (primary key `integration_id` and `name`), `kind`, `header_name`, `host`, `path_prefixes` `JSONB`, `binding_sha256`, `revoked_at` `TIMESTAMPTZ` null (the last revocation, D11), `env_var` `VARCHAR(96)` (the derived variable name, D11), `value_present` `BOOLEAN` not null default false and `value_seen_at` `TIMESTAMPTZ` null (both from the runner's last service view), `updated_at`. No column holds a secret value.

There is no table of tool reviews: a review is a rule of kind `integration_tool_review` of `add-action-approvals` (D13, owner answer 89.4 of 2026-10-08).

Indexes: `integration (tenant_id, created_at DESC)`, `integration_version (state) WHERE state IN ('building','awaiting_owner')`, and the conditional updates on `integration.state` and `integration.active_version`, and the partial unique index `integration_version_one_building_uk` on `integration_version (tenant_id, integration_id) WHERE state = 'building'` of D1.

The same migration adds this change's notification pair to the owner notification store of `add-shared-scheduler`, which keeps the allowed pairs in the table `owner_notification_kind (source, kind)` referred to by the foreign key `owner_notification_kind_fk` (owner answer 93 of 2026-10-08): `INSERT INTO owner_notification_kind (source, kind) VALUES ('integration', 'auto_disabled') ON CONFLICT DO NOTHING`.

Database links: this migration adds the foreign keys between its own tables and to the run and approval tables of earlier changes, and no foreign key to a tenants table (one tenant rule for tables of the dependency fix of 2026-10-05). `add-tenant-isolation` (company, build group 5) creates `tenants` later and adds `integration_tenant_fk` and the other tenant keys of these tables in its own migration. `integration` gets the unique constraint `integration_tenant_id_uk` on `(tenant_id, id)`, so a child row can name its parent together with its tenant and can never point at another tenant's integration:

| Constraint | Columns | References | On delete |
| :--- | :--- | :--- | :--- |
| `integration_version_integration_fk` | `(tenant_id, integration_id)` | `integration(tenant_id, id)` | `CASCADE` |
| `integration_version_build_run_fk` | `build_run_id` | `subagent_run(id)` | `SET NULL` |
| `integration_version_coding_run_fk` | `coding_run_id` | `coding_run(run_id)` of `add-coding-agent-delegation` | `SET NULL` |
| `integration_destination_integration_fk` | `(tenant_id, integration_id)` | `integration(tenant_id, id)` | `CASCADE` |
| `integration_credential_integration_fk` | `(tenant_id, integration_id)` | `integration(tenant_id, id)` | `CASCADE` |

`created_by` has no foreign key, because users live in the identity provider of `add-keycloak-login`, not in a table of the agent.

### D18: Metering

Usage is reported through the `UsageEventPort` of `add-deployment-modules`, whose default `NoOpUsageEventPort` does nothing. `add-usage-metering-and-quotas` (company, build group 5) registers its `UsageLedgerRecorder` backed implementation later, which turns these events into ledger rows. This change does not wait for it.

- Build: the coding run reports its `coding-agent` usage events with its own run id and the integration run as parent, and the dependency and verify workspaces report their `sandbox` usage events, both by the existing rules of the sibling changes.
- Calls: tool calls of integration entries report `mcp-tool` usage events because the entry is `metered: true`, with `provider` set to the metric tag `integration`.
- Running time: counted as the runner metric `sandbox.services.seconds`, not as a usage event (owner decision 65.7 of 2026-10-04, closed Open Question 1). If billing for it starts, it follows the sandbox pattern of `add-agent-sandbox`: one usage event of its own request type, sent when an integration container stops, with the tenant and the seconds it ran, the way a destroyed workspace sends its `sandbox` event.
- Quota: the coding run checks the `QuotaGate` port of `add-deployment-modules` before it starts and at every poll, the way `add-coding-agent-delegation` defines. Its default `AllowAllQuotaGate` allows every call, and `add-usage-metering-and-quotas` registers the real gate later. This change adds no quota port of its own.

### D19: Metrics, logs, traces and the banner

Agent metrics are in the specs (`integration.builds.started`, `integration.builds.finished`, `integration.build.duration`, `integration.count`, `integration.containers.running`, `integration.auto_disabled`, `integration.tool.failures`, `integration.actions`, `integration.credential.grants{outcome}`). Runner metrics: `sandbox.images.built{outcome}`, `sandbox.images.refused{reason}`, `sandbox.services.active`, `sandbox.services.restarts`, `sandbox.services.seconds`. No id, slug, tenant, tool or host as a tag.

Logs: MDC `tenant_id`, `integration_id`, `integration_version`, `subagent_run_id`. INFO per stage, state change and management action. WARN per refusal, rejected version, auto-disable and failed reconcile. Request texts, API notes, manifests and checker output only at DEBUG. Credential values never: the agent never holds one, and the runner never logs one.

Traces: the build is an `Observation` named `integration.build` with a span per stage, the runner calls are client spans under it, and the reconcile is `integration.reconcile`.

Banner block: whether the module is active, the runtime and verify image digests, the safety bounds, the number of integrations per state, the reserved memory of the running integration containers, and the number of credentials waiting for a value (never a variable value).

### D20: Audit, erasure and export

The ten actions of the `integration-management` spec are sent through the `AuditEventPort` of `add-deployment-modules` as `AuditEvent` values with the event name, tenant, actor, target and outcome, never a credential value, API notes or source text. Its default `LogAuditEventPort` writes one structured INFO line per event. `add-audit-and-gdpr-compliance` (company, build group 5) registers its `AuditRecorder` backed implementation later, and a test proves that a test bean replaces the default with no edit of this change.

Erasure and export are company work of `add-audit-and-gdpr-compliance`, which builds `IntegrationErasure` later on the repositories, the runner calls and the repository folder of this change. This change does not wait for it. What that change builds, recorded here so the stores of this change stay erasable: `IntegrationErasure.deleteTenant` stops and removes every runner object of the tenant through the runner, deletes the rows (cascading), the tenant's integration repository folder and the build reports in the object store. Export covers everything erasure removes. `exportUser` lists the integrations whose `created_by` is the user, with manifests and version states, never secret values. `exportTenant` holds everything `deleteTenant` removes: every `integration`, `integration_version`, `integration_destination`, and `integration_credential` row of the tenant (no secret value, because no column holds one) as JSON, the tenant's integration repository folder as its files at the newest commit plus a `git bundle`, and every build report under `tenant/<tenantId>/integration-builds/` of the `coding-output` bucket. Images and runner objects are built from the repository, so they are not exported, and the runner is not called. The tenant's approval requests and rules of the three integration kinds are erased and exported by the approval erasure of `add-audit-and-gdpr-compliance`. `deleteUser` sets `created_by` to null. Tenant erasure lists the variable names of the erased integrations in its result, so the owner can remove their lines from `integration-secrets.env`, which no service writes.

### D21: Errors

New `ApiErrorCode` values: `integration_not_found` (404), `integration_state_conflict` (409), `no_previous_version` (409), `credential_not_found` (404), `tool_review_not_found` (404). Runner codes: `archive_refused` (400), `service_not_found` (404). Refusals inside the five tools are tool results. A `USER` token on an owner endpoint gets 403 from the filter chain (D13), and a row of another tenant answers 404 `integration_not_found`. With the module `self-built-integrations` off, the controller does not exist and every endpoint answers 404, and a tenant without the module grant gets 403 `module_denied` of `add-deployment-modules`, so no `integrations_disabled` code exists.

### D22: Configuration

`IntegrationProperties` binds `app.integrations`: `safety.*` (D15), `build.network.allow`, `entry-refresh-interval` (60s, local, D25), `failure.max-consecutive-calls` (5), `failure.max-unhealthy` (5m), `max-result-chars` (20000, D10), `profiles.runtime` and `profiles.verify` (runner profile names). The feature is switched on only by the deployment module `self-built-integrations`, which requires `coding` and uses `self-improvement` (`uses: [self-improvement]`, D26) in the catalog of `add-deployment-modules`, and every bean of this change carries `@ConditionalOnModule("self-built-integrations")`. There is no `app.integrations.enabled` flag. The schedule of the reconcile is `app.scheduler.system-tasks.integration-reconcile.cron` and `.time-zone` of `add-shared-scheduler` (D25), not a key of `app.integrations`. The application refuses to start when a safety bound is above its maximum or when the build allow-list holds a wildcard.

Settings and environment variables (owner rule 98 of 2026-10-08): every value of this change with a default is a setting. `application.yaml` writes each key as `key: ${ENV:default}`, `IntegrationProperties` carries the same default in code, and the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`. ENV is Spring Boot's canonical environment form of the property (upper case, dots become underscores, hyphens removed). A list is one comma separated value. Task 5.2 builds them, task 6.1 the two reconcile keys and the refresh interval, task 9.7 documents them.

| Property | Environment variable | Default |
| :--- | :--- | :--- |
| `app.integrations.safety.container.cpus` | `APP_INTEGRATIONS_SAFETY_CONTAINER_CPUS` | `0.25` |
| `app.integrations.safety.container.memory-mib` | `APP_INTEGRATIONS_SAFETY_CONTAINER_MEMORYMIB` | `256` |
| `app.integrations.safety.container.pids` | `APP_INTEGRATIONS_SAFETY_CONTAINER_PIDS` | `128` |
| `app.integrations.safety.max-running-builds` | `APP_INTEGRATIONS_SAFETY_MAXRUNNINGBUILDS` | `1` |
| `app.integrations.safety.build.max-file-bytes` | `APP_INTEGRATIONS_SAFETY_BUILD_MAXFILEBYTES` | `1MB` |
| `app.integrations.safety.build.max-source-bytes` | `APP_INTEGRATIONS_SAFETY_BUILD_MAXSOURCEBYTES` | `5MB` |
| `app.integrations.safety.build.max-dependency-bytes` | `APP_INTEGRATIONS_SAFETY_BUILD_MAXDEPENDENCYBYTES` | `50MB` |
| `app.integrations.safety.build.command-timeout` | `APP_INTEGRATIONS_SAFETY_BUILD_COMMANDTIMEOUT` | `300s` |
| `app.integrations.safety.build.max-output-bytes` | `APP_INTEGRATIONS_SAFETY_BUILD_MAXOUTPUTBYTES` | `64KB` (the stored test and checker output of D6) |
| `app.integrations.safety.call-timeout` | `APP_INTEGRATIONS_SAFETY_CALLTIMEOUT` | `30s` |
| `app.integrations.build.network.allow` | `APP_INTEGRATIONS_BUILD_NETWORK_ALLOW` | `pypi.org,files.pythonhosted.org` |
| `app.integrations.entry-refresh-interval` | `APP_INTEGRATIONS_ENTRYREFRESHINTERVAL` | `60s` |
| `app.integrations.failure.max-consecutive-calls` | `APP_INTEGRATIONS_FAILURE_MAXCONSECUTIVECALLS` | `5` |
| `app.integrations.failure.max-unhealthy` | `APP_INTEGRATIONS_FAILURE_MAXUNHEALTHY` | `5m` |
| `app.integrations.max-result-chars` | `APP_INTEGRATIONS_MAXRESULTCHARS` | `20000` (the `max-result-chars` of every integration entry, D10) |
| `app.integrations.profiles.runtime` | `APP_INTEGRATIONS_PROFILES_RUNTIME` | `integration-runtime` |
| `app.integrations.profiles.verify` | `APP_INTEGRATIONS_PROFILES_VERIFY` | `integration-verify` |
| `app.scheduler.system-tasks.integration-reconcile.cron` | `APP_SCHEDULER_SYSTEMTASKS_INTEGRATIONRECONCILE_CRON` | `* * * * *` (quoted in the compose line, because it holds spaces and `*`) |
| `app.scheduler.system-tasks.integration-reconcile.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_INTEGRATIONRECONCILE_TIMEZONE` | `Europe/Warsaw` |

No `.env.example` line is added for them. The integration secrets `INTEGRATION_SECRET_<id12>_<NAME>` have no default and live only in `integration-secrets.env` of the runner (D11). The runner side of this change is already a setting of `add-agent-sandbox` (its settings table, rows in `docs/CONFIGURATION.md`): the archive bounds `app.runner.images.max-entries` (5000) and `app.runner.images.max-bytes` (60 MiB), `app.runner.images.max-per-integration` (2), `app.runner.images.orphan-age` (one day), the service limits and maxima `app.runner.services.limits.*` and `app.runner.services.maxima.*`, the proxy and gateway sizes `app.runner.services.sidecar.*` (0.1 CPU, 64 MiB, 64 processes), `app.runner.services.tmp-mib` (32) and `app.runner.services.restart-max-tries` (3). This change uses those values and adds no runner setting of its own.

Kept as constants, because they are not operational: the maxima of the D15 table (startup ceilings that only guard the configured value, while the runner's own maxima `app.runner.services.maxima.*` are settings of `add-agent-sandbox` and refuse a larger request in any case), the 1024 byte path limit of an archive entry (a format safety rule), the template's allowed paths and file names, the ports inside the private networks (the integration container's 8000 and the gateway's 8080 and 8081, fixed by the template image and `add-agent-sandbox` D16), the user id 10003 and the image names, the variable name pattern of D11, the slug length of D17 and every column size, the tool name and category mapping of D10, the trust, discovery and default mode of an integration entry (security rules), every error code, metric name, label, enum value and notification source and kind, and the test markers and test values of D23. The runtime image pins (the `python:3.12-slim` digest and the `fastmcp`, `httpx`, `pydantic` and `uvicorn` versions) stay read at implementation time by tasks 4.1 and 4.2.

### D23: Tests

- Fake coding agent: the fake installed under the real binary name `opencode` in the coding test image of `add-coding-agent-delegation` (owner answer 90 of 2026-10-08). This change adds an integration mode to that fake: a seed run whose workspace holds `BUILD_REQUEST.md` writes a fixed `quotes` integration from fixtures into the seed (one read tool, one credential), and follows markers in `BUILD_REQUEST.md`: `#add-destination`, `#extra-tool`, `#failing-test`, `#symlink`, `#change-outside-py`, `#sdist-dependency`, `#crash-on-call`. No setting, profile or overlay of the agent or the runner names the fake: a test picks the coding test image the way `add-coding-agent-delegation` picks it for its own tests.
- Fake outside system: a Mockoon container (`mockoon/cli`, pinned by version and digest) that loads the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` (owner answer 86.1 of 2026-10-08) and serves the fake quotes service under the path prefix `/fake-quotes/` (owner answer 86.4), on a test host name that the test's egress allow-list and approval name, whose rule answers only when the credential header carries the test value. Its request log (`GET /mockoon-admin/logs`) records every request, but Mockoon redacts authorization, cookie and API key headers there, so the header value is proved by that answer and never read from the log.
- Unit tests: input validation of each tool, the manifest comparison, the lock checks, the archive validator (each refusal), the state machine, the failure tracker, the tool name and category mapping, the variable name derivation, the configuration refusals.
- Integration tests (Testcontainers runner on Docker Desktop with `runc`, with a test `integration-secrets.env` written by the test itself, Testcontainers PostgreSQL, a Mockoon container that loads `scripted-model.json` as model provider and outside system, answer 86.1): a full build to `active` after both approvals, every fake marker rejected at the right stage with nothing kept, the image holding exactly the tested digests, the credential header reaching the fake outside system (its answer only for the test value) while no copy is found in the integration container (inspect, `/proc/1/environ`, a file search) or in any agent log or agent memory dump of the reconcile, a missing variable keeping the integration `awaiting_owner`, a runner recreate with a new value reaching the gateway, egress refused before approval and after rule removal, the agent unreachable from the integration, update with and without a new host, a denied new destination, rollback with the old review rules applying again, a credential revoke, remove leaving nothing labelled and no rule of the three integration kinds, the automatic disable after five failures with its owner notification, reconcile after an agent restart and after a runner restart, two agent instances (one reconcile per firing, one build per integration, an activation on one instance connected on the other and a disable withdrawn there, through the channel `mcp_runtime_entries` of `add-mcp-tool-servers`), tenant isolation of every endpoint.
- Runner tests: `POST /v1/images` refusals and the never-started container, services create, replace by part, delete and reaper rules, the secret read by derived name only, and the forbidden settings test covering services.
- The escape suite of `add-agent-sandbox` gains an integration container profile, and runs under `runsc` on a Linux host in task 9.2.
- Tenant rules and login roles: a migration test for every foreign key of D17, an integration test with two tenants bound through `TenantContext.runAs` for every integration store and for a call with no bound tenant (D16), and a filter chain test of every row of D13 with a `USER` token, an `ADMIN` token of the tenant and an `ADMIN` token of another tenant.
- End-to-end (owner decision 40.5 of 2026-10-02, and the owner request of 2026-10-04 that every planned change carries end-to-end tests, deterministic Bruno tests wherever no AI model is needed): two new specs in `apps/ascend-agent/e2e/`, each with the next free number at implementation time. The scripted model and the fake MCP server of the shared harness of `close-agent-test-gaps` (its design D5 and task group 4) start only for deterministic tests, never for AI-run e2e specs (owner answer 70.4 of 2026-10-04).
  - `<N>-integration-build-fake-coder`, deterministic: it runs in the deterministic phase of `close-agent-test-gaps` D7 (owner answers 70.4 of 2026-10-04 and 91.1 of 2026-10-08), in which only the agent is recreated, AscendMemory is faked under `/ascend-memory/` of `e2e-scripted-model`, and no spec wipes memories. The scripted model calls `integration_build` and the built tool, the fake `opencode` of the coding test image writes the fixed `quotes` integration, and the fake quotes service, served by the shared scripted model `e2e-scripted-model` under the path prefix `/fake-quotes/` (owner answer 82.5 of 2026-10-08), is the outside system at `http://e2e-scripted-model:3000/fake-quotes`. The egress proxy refuses a private address, so the spec reaches that one container only through a test-side overlay file of the runner that lists `e2e-scripted-model` as an allowed private host, applied only in the deterministic phase and never written into the runner's shipped configuration, a profile of it or the real `integration-secrets.env` (owner answer 90 of 2026-10-08). The overlay reaches the running runner by copy, the way `close-agent-test-gaps` D7 copies the agent's overlay (owner answer 98.1 of 2026-10-08): the spec runs last in the deterministic phase, after the coding spec of `add-coding-agent-delegation`, on the runner that the phase recreated with `SANDBOX_CODING_IMAGE` set, and before the spec this change copies `apps/ascend-agent/e2e/overlay/runner-application-e2e.yaml` into the runner's `/app/config/application.yaml` and restarts the runner. The end step of the phase recreates the runner from its image with nothing set, which removes the copied file and the test value, and the end check proves both (task 10.8). The credential value is the owner's real step: the spec writes its one variable line, with a test value that is not a secret, into the real `integration-secrets.env` next to `compose.yaml`, recreates the runner with the same command as the phase (`SANDBOX_CODING_IMAGE` set in its shell, because a recreate reads the environment again), copies the runner overlay into it again and restarts it, because a recreate starts from the image, and removes exactly that line in its cleanup, so no test secrets file and no setting points the runner elsewhere (owner answer 90). It proves the build, the report, both approvals with the variable name and no value, the owner's secrets file step with a runner recreate, activation, the tool review, a call that carries the credential header to the fake while the integration container holds no copy, and the login role rules with the Keycloak e2e users of tenant `default`. The check that an `ADMIN` of another tenant gets 404 is company work: `add-tenant-isolation` adds it to this spec in place later, with the test tenants of `add-auth-and-identity`. This change does not wait for it.
  - `<N>-integration-open-meteo-real`, AI-run: a real chat model decides to build an integration for the Open-Meteo forecast API (`api.open-meteo.com`, no key, no credential) and real OpenCode writes it, the spec approves its egress through `/api/v1/approvals`, reviews its tool, calls it from a chat for a fixed city, disables and removes it, and checks that nothing of it is left. It runs alone.
  - Not provable end to end, and proven by the integration, runner and escape tests above instead: the lifecycle that the removed spec `<N>-integration-lifecycle-fake-coder` repeated (disable and enable, an update with and without a new destination, a denied new destination, rollback, a failing build that keeps nothing, the automatic disable after five failed calls, a credential revoke, and a remove that leaves no row, runner object or rule), because each only repeats an integration test above (owner answer 91.3 of 2026-10-08), every fake marker refused at its own stage, the reconcile after an agent or runner restart, the agent unreachable from the integration container, and the self-change records and their undo (integration tests of tasks 10.4 and 10.5). The audit records, erasure and export and the metering rows are company work, proven in `add-audit-and-gdpr-compliance` and `add-usage-metering-and-quotas` when they register their implementations.

### D24: Threat model

| Threat | Control |
| :--- | :--- |
| Generated code reads secrets | No secret in the coding workspace, the verify workspaces or the integration container. The gateway adds the value |
| The agent leaks a secret | The agent never holds an integration secret. Only the runner reads it from its own environment, by a name it derives itself |
| Generated code sends data to an unapproved host | Internal network, proxy with approved hosts only, no DNS, egress approval per host |
| Generated code reaches the agent or internal services | Integration only on its own internal network, the agent reached through the gateway only, proxy refuses private addresses |
| The coding agent widens the integration's rights | The manifest must equal the request, `outside.py` is fixed, changed paths are checked |
| A test run fakes success | Tests and the contract check run in workspaces the agent controls, from a checker in the image |
| Build steps escape | No build steps: dependency install runs no package code, image assembly runs nothing |
| A changed tool runs under an old review | Reviews keyed by definition digest, approvals refuse `tool_changed` |
| A credential is sent to another host | Gateway route with one fixed upstream host and path prefixes, binding change needs a new approval |
| Prompt injection asks for the secret in the chat | No tool reads or returns a value, the tool result and the prompt tell the model never to ask, and the value goes only into the runner's file |
| One tenant uses another's integration | Tenant keys on rows, entries, index entries and runner labels, and the runner derives the variable name from the integration id and checks the tenant label of the service |
| A failing integration burns money or calls | Auto-disable, call timeout, usage events for every metered tool call, and the `QuotaGate` on model spend, whose real implementation `add-usage-metering-and-quotas` registers later |

### D25: Periodic work: the reconcile on the shared scheduler, entry registration local

The rule of `add-shared-scheduler` D2 applies: work that writes shared state runs once per deployment on the shared scheduler, and work that only refreshes one instance's memory stays local.

Shared: the system task `integration-reconcile` of `add-shared-scheduler`, a value of its `SchedulerTaskName` enum that this change adds, registered by a bean with `@ConditionalOnModule("self-built-integrations")` under that change's registration contract. Its schedule is the five field cron `app.scheduler.system-tasks.integration-reconcile.cron` (default `* * * * *`, every minute) with `.time-zone` (default `Europe/Warsaw`). Each firing runs on exactly one agent instance. It reads the integrations that should run from the rows and the approved hosts from the remembered rules (D12), reads the runner's services, starts the missing ones, replaces what changed through `PUT /v1/services/{id}` (which changes nothing when the spec digest is equal, D8), stops the ones that should not run, and writes the runner's view (`health`, `restartCount`, `value_present`) into the rows for the view and the failure tracker (D14). A failed firing is logged at WARN and retried at the next one.

Immediate reactions on one instance: `ApprovalRuleChangedEvent` (D12), an activation, a disable, a removal and a credential revocation (D11) reconcile that one integration at once on the instance where they happen, after commit. That is safe beside a running firing, because the runner calls are idempotent and the state moves are conditional updates.

Local: the MCP entries. Each agent instance holds its own MCP clients in `RuntimeMcpClientRegistry` of `add-mcp-tool-servers`, so each instance holds the entries of `IntegrationMcpEntrySource` itself. `IntegrationMcpEntrySource.entries()` lists, from the shared integration rows and never from a list in memory, the MCP entry of every integration whose state makes it serve tools, in the entry shape of D10. Wherever this change calls `McpServerRegistry.add` or `remove` (an activation, an update, a rollback, a disable by the owner, the model or the failure rule, an enable, a removal, a revocation, a rule change, and the startup adoption), it does so in the transaction that changes the integration row, so the notification that `add-mcp-tool-servers` sends reaches every agent instance only after the commit.

Several agent instances (answer 87 of 2026-10-08, CANON 26.1): a disabled, removed or rolled back integration must not stay callable on another instance, so the entries use the one cross-instance signal of `add-mcp-tool-servers` D10: `McpServerRegistry.add` and `remove` send `pg_notify('mcp_runtime_entries', <source name>)` through the one `PostgresNotificationListener` of `add-keycloak-login` D20, and on every instance a handler reads `IntegrationMcpEntrySource.entries()` again and connects, replaces or closes its own clients until they match, also in `onReconnect()` and once at startup before readiness. This change adds no channel of its own. The refresh every `app.integrations.entry-refresh-interval` (default 60 seconds) stays as the bound when a notification is lost, through `@Scheduled` on Spring Boot's auto-configured `TaskScheduler` (owner answer 89.3 of 2026-10-08). It only refreshes one instance's memory, so it never runs on the shared scheduler.

### D26: Self-improvement change records and their undo

`add-self-improvement` (build group 4, position 13) lands before this change and offers two seams (its D11 and D13): `SelfChangeRecorder.recordIntegrationEvent(...)` and the port `SelfChangeUndoHandler`. This change uses both, and only while the module `self-improvement` is active. The module `self-built-integrations` therefore lists `self-improvement` under `uses` in the catalog of `add-deployment-modules`, an optional reference: `IntegrationSelfChangeReporter` takes `ObjectProvider<SelfChangeRecorder>` and records nothing when the bean is absent, and `IntegrationSelfChangeUndoHandler` carries `@ConditionalOnModule("self-improvement")` next to `@ConditionalOnModule("self-built-integrations")`.

Recording: after commit of the state change, `IntegrationSelfChangeReporter` calls `recordIntegrationEvent` once per event with the tenant, the integration id, the version, the operation, the reason text and the request id that started the action (null for an automatic disable). The five events:

| Operation | When | Reason text |
| :--- | :--- | :--- |
| `register` | the first version of an integration becomes `active` | the build request's purpose |
| `activate` | a later version that waited in `awaiting_owner` becomes `active` through the handler of its last approval (D13) | the update request's change text |
| `update` | a later version replaces the active one at once, with no new host or changed credential (D13) | the update request's change text |
| `disable` | the model disables the integration through `integration_disable` | the reason the model gave |
| `auto_disable` | the failure tracker moves the integration to `disabled_failing` (D14) | the failure rule that fired and its count |

A disable by the owner through `POST /api/v1/integrations/{id}/disable`, an enable, a rollback and a remove are owner actions and are not recorded as self changes. They stay in the audit events of D20. A failed call to the recorder is logged at WARN and never undoes the state change it reports, because the integration's own state and audit event are the source of truth.

Undo: `IntegrationSelfChangeUndoHandler` returns `type()` `integration` and, in `undo(change, identity)`, calls this change's own paths as the deciding identity, the actor kind `owner`, so the audit event of D20 names the owner:

| Operation of the record | Undo |
| :--- | :--- |
| `register`, `activate` | the disable path of `POST /api/v1/integrations/{id}/disable` |
| `update` | the rollback path of `POST /api/v1/integrations/{id}/rollback` |
| `disable`, `auto_disable` | the enable path of `POST /api/v1/integrations/{id}/enable` |

`SelfImprovementService.undo` applies the newest rule (`newer_change_exists`) and `already_undone` before it calls the handler. A refusal of this change's path, for example `no_previous_version` or `integration_state_conflict`, or `integration_not_found` for a removed integration, is returned unchanged as the undo's problem detail. The undo actions write their own `integration.actions` sample and INFO line like any other management action.

## Required edits to other changes

This change edits no other change. Each edit belongs to the named change. Each heading says whether the edit is already made in the named change, checked against that change's text, and where. Every change of build groups 3 and 4 named below lands earlier and has made its edit, and a company change of build group 5 lands later and plugs in by itself, so no task of this change is blocked by an edit.

### `add-agent-sandbox`

Made in that change: edits 1 to 7 in its D6, D7, D8, D9, D13 and D17 (listed there under the edits this change asked of it), and edit 8 in its D16.

1. Design D3 and spec `agent-sandbox-runner`: `POST /v1/images` and `DELETE /v1/images/{id}` of D7, with the code `archive_refused`, and the rule that the runner creates image containers that are never started.
2. Design D3, D6, D8 and the spec: the `/v1/services` API of D8 for long-lived integration services, their network, proxy and gateway, the label `ascend.sandbox.kind` values `service`, `image` and `gateway`, the reaper rules of D8, and the adoption of existing services by their labels when the runner starts. There is no count limit on services (owner decision 40.4).
3. Design D7: two image profiles `integration-runtime` and `integration-verify` from `infra/integrations/images/`, the runtime profile used only for images and services.
4. Design D6: the egress proxy is recreated, never reloaded, when its allow list changes.
5. Design D13: the runner metrics of D19, including `sandbox.services.reserved.memory`.
6. Compose: the network `integrations-ingress` (`internal: true`) that the agent joins and the runner attaches gateways to.
7. Design D4 and the spec: integration secrets (D11). The runner reads `INTEGRATION_SECRET_<id12>_<NAME>` from its own environment, given only by `env_file: [{ path: integration-secrets.env, required: false }]` on `ascend-sandbox-runner`, resolves a credential route of `PUT /v1/services/{id}` by the variable name it derives from the service's integration id, never accepts a value or another variable name from the caller, never returns, logs or labels a value, and reports `secretPresent` per route.
8. Design D16, the per-workspace credential gateway that change owns: the gateway gains a route kind `inbound` that listens on its own port, forwards to a fixed container address on its internal network and adds no header, and credential routes listen only on their own port. This edit was listed under `add-coding-agent-delegation` before, but the gateway and its route kinds belong to `add-agent-sandbox` D16.

### `add-coding-agent-delegation`

Made in that change: edit 1 in its D3, D6, D8, D14 and D21 and its `coding-delegation` spec, and edit 2 in its D3 and D15.

1. Design D3 and spec `coding-delegation`: a coding run with source `seed`, started by trusted agent code through an internal entry point (`CodingRunService.startSeeded`) and never by a tool, with the seed written as the base commit, a `purpose` (`integration`), the egress allow-list given by the caller, and no publish (`coding_not_publishable`).
2. Design D3 and D15: the project carries `source_kind` (`github`, `new_project`, `seed`) and `purpose`.

### `add-action-approvals`

Made in that change: edit 1 in its D3 and edit 2 in its D9 and its `action-approval-decisions` spec.

1. Design D3: the handlers of `integration_credential` and `integration_egress` are provided by this change, the way `personality_change` is provided by `add-agent-soul`.
2. Design D9 and D11: `ApprovalRuleChangedEvent` published after commit when a rule is created, replaced or removed, and `ApprovalService.deleteRules(tenantId, kind, scopePrefix)` for the removal of an integration.
3. Answer 89.4 of 2026-10-08, made there: kind `integration_credential` always remembers an `allow` rule on approve, scoped to the integration, the credential name and the binding digest, the new rule-only kind `integration_tool_review` with category `tool_review`, and `ApprovalService.putRule`, which this change calls from its tool review endpoint.

### `add-shared-scheduler`

Edit 1 is made in that change, checked on 2026-10-03: its D2 inventory holds the system task row and the local work row for the registration of integration MCP entries.

1. Design D2, the inventory: a row for the system task `integration-reconcile` of this change (owner `add-self-built-integrations`, home shared, every minute, default `* * * * *` in `Europe/Warsaw`, module `self-built-integrations`), and a row for the registration of integration MCP entries as local work, per instance, every `app.integrations.entry-refresh-interval` (D25). `SchedulerTaskName` gains the value `integration-reconcile`, added by this change when it lands.
2. Answers 89.6 and 93 of 2026-10-08: this change adds the source `integration` with the kind `auto_disabled` to `owner_notification_kind` in its own migration (D17) and creates the notification of an automatic disable through `OwnerNotificationService` (D14).

### `add-agent-subagents`

Made in that change: edits 1 to 4 in its D10, D13 and D16 (its row for this change under the edits other changes asked of it).

1. The run kind `integration` is in the kind set that change owns (`subagent`, `approval`, `coding`, `scheduled`, `self_review`, `integration`), with `subagent_name` holding the slug.
2. The closed failure set gains `INTEGRATION_VERIFY_FAILED` and `INTEGRATION_IMAGE_FAILED`.
3. Design D10: runs of kind `integration` use the pool `integration`, registered by this change in the one slot pool `RunSlots` of that change through a `RunPoolRegistration` bean, bounded by the safety bound `max-running-builds` with no waiting bound (answer 89.7 of 2026-10-08). Made there.
4. Design D16: the finished runs block lists integration runs and automatic disables once.

### `add-agent-skills`

Made in that change: edits 1 and 2 in its D5, D7 and D18 (its row for this change under the edits other changes asked of it).

1. Design D7: the tenant folder gains the repository `integrations/`, read and written only by this change, next to `skills/` and `.claude/agents/`.
2. Design D18: tool entries may be tenant-keyed (also asked by `add-mcp-tool-servers`). Storing the `tool` entry of a tenant-scoped server entry (an integration) as a tenant entry is done by this change (task 7.3), moved here from `add-agent-skills` task 10.10 (dependency fix of 2026-10-05).

### `add-tenant-policy`

Company, build group 5, lands later and plugs in through the `TenantToolPolicy` port of `add-agent-subagents`. This change does not wait for it. Made in that change: edits 1 and 2 in its design D2 and D8 (its tool table lists the five tools and the entry `integrations:own`, off for a new tenant and listed in the personal default) and its `tool-policy` spec. Its policy test of this change's tools (former task 10.2 here) moved there (dependency fix of 2026-10-05).

1. Design D2: `integration_build`, `integration_update`, `integration_request_credential`, `integration_list` and `integration_disable` ship off for a new tenant, and the personal deployment's default lists them.
2. A new allow-list entry `integrations:own` that allows the tools of the tenant's own integrations, in the default of the personal deployment and off for a new tenant.

### `add-audit-and-gdpr-compliance`

Company, build group 5, lands later and plugs in through the `AuditEventPort` of `add-deployment-modules`. This change does not wait for it. Made in that change: edit 1 in its design and its `audit-logging` spec (the ten `INTEGRATION_*` actions), and edit 2 in its design, its `data-erasure` and `data-portability` specs, its proposal and its task 8b.2 (`IntegrationErasure`, `created_by` set to null for a user, every integration of a tenant removed, and a tenant export through `IntegrationErasure.exportTenant` that holds the rows, the repository folder and the build reports that erasure removes). The erasure and export task of this change (former task 10.3 here) and the erasure and export scenarios of the `integration-management` spec moved there (dependency fix of 2026-10-05).

1. Audit vocabulary: the ten `INTEGRATION_*` actions of the `integration-management` spec, never with a credential value, API notes or source text, recorded by its `AuditEventPort` implementation.
2. Erasure and export of D20.

### `harden-cloud-deployment`

`harden-cloud-deployment` is build group 3, position 4 and lands earlier, so its task 10.6 (the VM guide step for integrations) moved here (dependency fix of 2026-10-05). When this change lands, `docs/DEPLOYMENT.md` has the cloud VM section of that change, and this change adds the step itself (task 9.3) and a `production-deployment` delta (MODIFIED requirements "Credentials flow from the environment with a production startup guard" and "The deployment guide covers one cloud VM per customer").

1. `docs/DEPLOYMENT.md`: sizing of D8 and D15, the `integrations-ingress` network, and the file `integration-secrets.env` (file mode 600, owned by the deploy user, in the same backup rule as `.env`, never in git). Integration secrets never go into `.env`. They live in `integration-secrets.env` next to `compose.yaml`, which only `ascend-sandbox-runner` reads. Sizing: one integration container by default 0.25 CPU, 256 MiB and 128 processes, at most 1.0 CPU, 1024 MiB and 512 processes, plus 0.1 CPU, 64 MiB and 64 processes each for its egress proxy and its credential gateway, so one running integration reserves 384 MiB and 0.45 CPU at the defaults, with no count limit and the reserved memory reported as `sandbox.services.reserved.memory`. The `integrations-ingress` network is `internal: true` and joined only by the agent and the credential gateways.

### `add-tenant-isolation`

Company, build group 5, lands later. This change does not wait for it. By the one tenant rule for tables of the dependency fix of 2026-10-05, `add-tenant-isolation` creates `tenants` and, in its own Flyway migration, adds the foreign keys to `tenants(id)` on every table that exists when it lands. The list of this change's tables is in its inbox for phase B of that fix.

1. Its decision 14 and its `tenant-isolation` capability list the integration tables (`integration`, `integration_version`, `integration_destination`, `integration_credential`, `integration_tool_review`, each with `tenant_id`, its foreign key to `tenants(id)` added by its own migration), the repository `tenants/<tenantId>/integrations/`, the prefix `tenant/<tenantId>/integration-builds/` of the `coding-output` bucket and the tenant label of every runner object of an integration, with the fail closed rule (D16).
2. The e2e check that an `ADMIN` of another tenant gets 404 on an integration, added in place to the spec of task 10.9 with the test tenants of `add-auth-and-identity`.

### `add-self-improvement`

Made in that change: edit 1 in its D11 and D13 and its `self-improvement-reports` spec, and edit 2 in its D2 (its row for this change under its required edits).

1. Its change records gain the five integration events `register`, `activate`, `update`, `disable` (by the model) and `auto_disable`, recorded through `SelfChangeRecorder.recordIntegrationEvent(...)`, each with its undo through a `SelfChangeUndoHandler` of type `integration` (`disable` for a registration or activation, `rollback` for an update, `enable` for a disable or an automatic disable).
2. Its review may suggest an integration in its report but has no integration tool and never starts a build (owner decision 40.3 of 2026-10-02).

Asked of this change by `add-self-improvement`, made here (D26, the `integration-management` spec and tasks 10.4 and 10.5): call `SelfChangeRecorder.recordIntegrationEvent(...)` after commit for the five events, only while the module `self-improvement` is active, and provide the `SelfChangeUndoHandler` of type `integration` that disables, rolls back or enables through this change's own paths as the deciding identity.

### Applied in other changes

- `add-mcp-tool-servers`: entry sources and run-time entries, tenant-scoped entries with tenant-keyed tool entries, the metric tag, and per tool modes from a source are written into that change (its D7, D8, D10 and D13 and its `mcp-tool-servers` spec), so its former edits 1 to 4 asked here are done there.
- `add-openclaw-plugin-host`: it lands earlier and posts the Discord approval prompt (its D12). The fixed line on an `integration_credential` prompt moved here from its task 5.4 and its `channel-approvals` spec (D11, task 10.6, the `integration-approvals` spec).
- `add-deployment-modules`: its edits 1 and 2 to this change are applied here (D21, D22): the module `self-built-integrations` that requires `coding`, no `app.integrations.enabled`, no `integrations_disabled`, and every integration's MCP entry belongs to the module.

### Checked, no edit needed

- `upgrade-spring-boot-4`: this change adds its codes to `ApiErrorCode` itself and uses Spring AI 2.0.1 and MCP Java SDK 2.0.0 as that change pins them.
- `add-usage-metering-and-quotas` (company, build group 5, lands later): it registers its `UsageEventPort` implementation and the quota gate later, and this change only sends usage events (D18). Its secret encryption is not used, because integration secrets are environment variables of the runner (owner decision 40.1).
- `add-flutter-chat-app`: the approval cards of `add-action-approvals` already show both kinds, and the credential card shows the variable name from the preview.
- `mcp-startup-resilience` (archived): see proposal.md, Modified Capabilities.

## Risks / Trade-offs

- [gVisor lacks a system call the runtime needs] → the runtime and verify images are tested under `runsc` in task 9.2, and the template uses only plain HTTP clients.
- [A destination host that serves user content (for example a paste site) lets an approved integration leak data] → the egress preview shows the host and its purpose, and the owner decides per host.
- [The owner approves a host without reading] → per host, never remembered for other integrations, removable at any time from the rule list.
- [The fixed header model does not fit an outside API] → refused at build time with a clear code, and a configured MCP server is the way for it.
- [`docker commit` behaves differently on the containerd image store] → measured in task 2.3 on both stores before the design is final.
- [A new or changed secret needs a recreate of the runner] → accepted minus of owner decision 40.1. The integration containers keep running, the runner adopts them by label, and the owner recreates the runner when no build runs.
- [The secrets file sits in plain text on the host, like `.env`] → the same trade the rest of the stack makes, file mode 600, never in git, and only the runner reads it.
- [Without limits, a model writes poor integrations repeatedly or many integrations crowd the host] → accepted by owner decision 40.4. Every tool asks first until reviewed, every build is a visible run with its cost in its run view and its usage events, each container is bounded, the reserved memory is on the banner and a metric, and the owner can disable or remove any integration.
- [A supply chain attack through a locked wheel] → hashes pin the exact files, the code runs only inside gVisor with only approved hosts, and no secret is in its process.

## Migration Plan

1. Land as build group 4, position 14 of the owner build order of 2026-10-04, after `add-self-improvement` and every other change it needs. No task waits for a company change of build group 5 (owner rule of 2026-10-04): `add-tenant-isolation`, `add-tenant-policy`, `add-audit-and-gdpr-compliance` and `add-usage-metering-and-quotas` register their implementations later. The required edits to `add-shared-scheduler`, `add-agent-sandbox`, `add-coding-agent-delegation`, `add-action-approvals`, `add-agent-subagents`, `add-agent-skills`, `add-self-improvement` and `harden-cloud-deployment` are made in those changes. The edits to the company changes are listings of this change's stores, tools and actions there.
2. Build the runtime and verify images, write their digests into the runner profiles, add `integrations-ingress` and the optional `env_file` to compose, and start the stack. Flyway creates the tables.
3. The feature stays off until the owner adds `self-built-integrations` to `COMPOSE_PROFILES`.
4. Rollback: remove `self-built-integrations` from `COMPOSE_PROFILES` and run `docker compose up -d`. The tools and endpoints disappear, and the system task `integration-reconcile`, registered only while the module is active, no longer runs. The owner removes the remaining integration services with the documented runner command in `docs/INTEGRATIONS.md`. The tables and the repository stay and are ignored. Flyway runs forward only, so dropping the tables is a new migration written only if the owner asks.

## Owner decisions of 2026-10-02

1. 40.1: integration secrets are environment variables given through docker compose, not a database table (D11).
2. 40.2: images are assembled by the runner through the Engine API, by copying the tested files into a fixed base image (D7).
3. 40.3: the self-improvement review only suggests a build in its report and never starts one.
4. 40.4: no limits, only the technical safety bounds of D15.
5. 40.5: the end-to-end spec builds an integration for Open-Meteo (D23).

Owner decisions of 2026-10-03: the sandbox is core and always on, so no module requires it (Context, D22). `add-tenant-isolation` and `add-auth-and-identity` land before this change, so this change adds its own foreign keys (D17), its own tenant rules (D16) and its own rows of the authorization matrix (D13) (superseded by the owner build order of 2026-10-04). Note of 2026-10-04: the matrix is now `add-keycloak-login`'s, which lands before this change, and the owner rule of 2026-10-04 puts `add-tenant-isolation` and `add-auth-and-identity` last, as company work. So this change keeps its tenant rules (D16) and its matrix rows (D13), and adds no foreign key to `tenants(id)`, which `add-tenant-isolation` adds later (D17, dependency fix of 2026-10-05).

## Owner decisions of 2026-10-06

- Answer 72.9: the two-tenant integration tests stay in this change (the `IntegrationTenantIsolationIT` of task 9.6 and the filter chain test with an `ADMIN` token of another tenant). They bind the tenants through `TenantContext.runAs` of `add-keycloak-login` and need no company change.
- Answer 72.1: `harden-cloud-deployment` moved to build group 3, position 4. It still lands before this change, so the VM guide step and the `production-deployment` delta of this change stay as written.
- Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. Its tables start empty, and it needs none of today's data.

## Owner decisions of 2026-10-07

Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): items 31, 34 and 69 are fixed here. Item 31: the gateway image is the credential gateway of `add-agent-sandbox` D16, not of `add-coding-agent-delegation` (D9 and the proposal). Item 34, answer 75.4: the scenario lists of task 10.12 are written from this change's requirements. Item 69: no task is marked blocked by a required edit (proposal and "Required edits to other changes").

## Owner decisions of 2026-10-08

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/integrations/` (task 10.8).

Answer 76.2 (the owner strongly prefers Mockoon, and no group 3 to 5 change uses the earlier mock server any more), applied to this change's own tests and confirmed by owner answer 78.3 of 2026-10-08 (unit tests use the JDK `HttpServer`, integration and e2e fakes use Mockoon containers): the fake outside system of the integration tests (D23, tasks 8.1 and 8.4) and the throwaway container `e2e-fake-quotes` of the deterministic spec (tasks 10.8 and 10.9) are a Mockoon container (the `mockoon/cli` image, pinned by version and digest) with its own environment file (`apps/ascend-agent/e2e/fixtures/fake-quotes/fake-quotes.json` for `e2e-fake-quotes`). For the deterministic spec the container and its file are superseded by answer 82.5 below. The integration tests keep their own Mockoon container. Mockoon redacts authorization, cookie and API key headers in its request log, so the credential header value is proved by the fake's answer, which it gives only for the test value, and never read from the log (spec `integration-management`).

Answer 78.3: both kinds of fake stay for this change's own tests: unit tests use the JDK `HttpServer`, and integration and e2e fakes use Mockoon containers. This confirms the application recorded in the answer 76.2 entry above.

Answer 78.4: the name `apps/ascend-agent/e2e/fixtures/fake-quotes/fake-quotes.json` of the fake outside system's environment file stays. Superseded by answer 82.5 below: the rules move into `scripted-model.json`, and the reply files into `scripted-model/responses/fake-quotes/`.

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (tasks 10.9 and 10.10).

Answer 81.3, addition (mandatory): every host and port of this change follows the rules of `close-agent-test-gaps` D8, so the plan works on Linux Docker Engine, where `host.docker.internal` does not resolve by itself. Checked on 2026-10-08: the integration container, its gateway and the fake outside system (now `e2e-scripted-model`, answer 82.5 below) reach each other by container name or network alias (`http://gateway:8080`, `http://integration:8000`, `http://int-<id12>:8081`, rule 1), and the verify run of task 4.3 uses `--network none` and calls nothing (rule 5). Bruno on the host reads the request log of `e2e-fake-quotes` (`fake-quotes-requests.yml` of task 10.9), so by rule 2 that container publishes its admin port on `127.0.0.1` only. Its host port is not decided (open question 2). Answer 82.5 below replaces that container with `e2e-scripted-model`, whose admin API is on `127.0.0.1:7033`. The mentions of Docker Desktop describe the development engine and name no address.

Answer 82.5 (the owner called the earlier design overengineered and not best practice): one Mockoon container, `e2e-scripted-model` of `close-agent-test-gaps`, serves every HTTP fake of the plans, the fake quotes service of this change included. The container `e2e-fake-quotes`, its environment file `fake-quotes.json` and its host port are removed. Its routes and rules live in the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` under the path prefix `/fake-quotes/`, which no other fake uses (`close-agent-test-gaps` D5 lists the prefix of every fake), so the quote route is `GET /fake-quotes/v1/quote`, and its reply files live in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/fake-quotes/`. Global variables of this fake, if any, start with `fake_quotes_`. The fixed `quotes` integration of the fake coder reaches `http://e2e-scripted-model:3000/fake-quotes` (container port 3000, `close-agent-test-gaps` D8 rule 1), its egress approval names the host `e2e-scripted-model`, and the runner's e2e overlay lets the egress proxy reach that one container. Bruno reads the request log at `http://127.0.0.1:7033/mockoon-admin/logs` and keeps only the requests whose path starts with `/fake-quotes/`. The deterministic specs therefore run in the harness phase of `close-agent-test-gaps` D7, serial with every other spec that uses the harness, and the phase runs exactly two test containers, `e2e-scripted-model` and `e2e-fake-mcp`. The egress allow entry lets the integration reach the scripted model's other routes too, which is accepted, because it exists only in the e2e overlay. The integration tests of D23 (Testcontainers) keep their own Mockoon container, and unit tests keep the JDK `HttpServer` (answer 78.3) (D23, tasks 10.8, 10.9 and 10.10).

Answer 85.1: no plan text of this change exports a key or a secret in a shell. Integration secrets live only in `integration-secrets.env`, which only the sandbox runner reads, and every other key in the repository `.env`. The deterministic spec writes its one test value, which is not a secret, as a line of `integration-secrets.env` and removes it in its cleanup (D23, task 10.9).

Answer 86.1: the Mockoon container of the integration tests (Testcontainers) loads the same shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` as the deterministic phase, as model provider and as the fake outside system (D23, tasks 8.1 and 8.4). Answer 86.4: its route prefix `/fake-quotes/` stays.

Answer 87 (rule R1, several agent instances, CANON 26.1): checked for every mechanism of this change, and the multi-instance machinery is kept: the system task `integration-reconcile` runs once per firing in the cluster, the immediate reconcile of one integration after a change runs on the instance that made it, state moves are conditional updates, and the runner calls are idempotent (D25). Changed: the build slots are the pool `integration` of the one slot pool in Postgres (D1), one build per integration is held by the partial unique index `integration_version_one_building_uk` (D1, D17), the credential request relies on the duplicate rule of the approval service instead of a copied state (D11), and the run-time MCP entry of an integration reaches every agent instance through the channel `mcp_runtime_entries` of `add-mcp-tool-servers` D10, with `IntegrationMcpEntrySource.entries()` reading the entries from the shared integration rows and the registry calls made in the transaction that changes the row, so a disabled integration is withdrawn on every instance at once, with the 60 second refresh as fallback (D25, tasks 6.1 and 7.1). The local refresh runs through `@Scheduled` on Spring Boot's auto-configured `TaskScheduler` (answer 89.3).

Answer 89.4: `approval_request` is the only record of an approval and `approval_rule` the only record of a remembered decision (`add-action-approvals`). This change stops copying decisions: `integration_destination` loses `approval_id` and `last_decision`, `integration_credential` loses `state` and `approval_id` and gains `revoked_at`, and the table `integration_tool_review` is replaced by rules of kind `integration_tool_review`. The credential approval, the egress approval, the tool review routes, the states in the views, revocation and rollback all stay, read from the approval and rule records (D10 to D13, D17, D20, the specs, tasks 5.1, 7.2, 8.1 to 8.4 and 9.1).

Answer 89.6: an automatic disable also creates an owner notification of source `integration` and kind `auto_disabled` through `OwnerNotificationService`, one per `ADMIN` of the tenant, in the transaction of the disable, beside the finished runs block, the audit event and the self-improvement record (D14, task 6.4). The Approve and Deny buttons of a credential approval prompt on Discord are the action types `approval_approve` and `approval_deny` of the one action endpoint `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host` (D11).

Answer 89.7: the build slot pool is one pool, `integration`, of the one slot pool `RunSlots` of `add-agent-subagents` (its D10), registered with a `RunPoolRegistration` bean from the safety bound `max-running-builds` with no waiting bound. The counts live in Postgres, so the bound holds with several agent instances (answer 87) (D1, task 5.2). This change has no retention task, so the retention part of answer 89.7 changes nothing here.

Answer 89.10: one production startup guard, `ProductionStartupGuard` of `add-keycloak-login`, with required placeholders in `application-production.yaml`. The MODIFIED requirement "Credentials flow from the environment with a production startup guard" of the `production-deployment` spec of this change now carries the new base text of `harden-cloud-deployment` (unset credentials stop start-up with Spring's error, blank or weak values are refused by the one guard) together with this change's own sentence on `integration-secrets.env`.

Answer 90: no test code and no test-only setting in real configuration. The e2e overlay pick of `fake-integration-coder`, the egress allowance for `e2e-scripted-model` in the runner's configuration and the runner's test secrets file `integration-secrets.e2e.env` are removed. The fake coder is an integration mode of the fake installed under the real binary name `opencode` in the coding test image of `add-coding-agent-delegation`, the egress allowance for `e2e-scripted-model` lives only in a test-side overlay file of the runner used in the deterministic phase, and the deterministic spec writes its test value into the real `integration-secrets.env` and removes it again (D23, tasks 10.8 and 10.9). Not decided: how a test-side overlay reaches the real `ascend-sandbox-runner` compose service without `-f`, the same open point as the agent overlay mount of `close-agent-test-gaps` task 4.5. Listed for the owner. (Decided by owner answer 98.1 of 2026-10-08, below: the overlay is copied into the running runner.)

Answer 91.1: the deterministic spec of task 10.9 runs in the deterministic phase of `close-agent-test-gaps` D7: only the agent is recreated, AscendMemory is faked under `/ascend-memory/` of `e2e-scripted-model` and never restarted, and no deterministic spec wipes memories. The memory wipes of tasks 10.9 and 10.10 are removed, and the approved fix above no longer applies to this change. The AI-run spec of task 10.11 uses the real AscendMemory. Answer 91.2: the fake MCP server of the harness is the one fake MCP server class of `close-agent-test-gaps` task 4.2, and this change writes no fake MCP server of its own.

Answer 91.3: the deterministic lifecycle spec `<N>-integration-lifecycle-fake-coder` (task 10.10) is removed, because each of its checks repeats an integration test of D23. With it go the scripted model rules `build-quotes-failing-test`, `build-quotes-crash-on-call` and `update-quotes-new-destination`. The build spec of task 10.9 stays, because it alone proves the live compose wiring (the `integrations-ingress` network, the runner's `env_file`, the real approval flow and the credential header through the gateway), and the AI-run spec of task 10.11 stays, because it runs with real AI answers (D23, tasks 10.8, 10.12 and 10.13, the `integration-management` spec).

Answer 93: the two tenant header names become one, `X-Ascend-Tenant`, so the runner calls of this change send the tenant in `X-Ascend-Tenant` (D7, D16, task 9.6). This change adds its notification pair `('integration', 'auto_disabled')` to `owner_notification_kind` in its own migration (D17, task 5.1).

Answer 98 (owner rule 98, every value with a default is a setting): the settings table under D22 lists every value of this change with a default, with its property, environment variable and default. The agent writes each as `${ENV:default}` in `application.yaml` with the same default in `IntegrationProperties` and `- ENV=${ENV:-default}` on the `ascend-agent` compose service (tasks 5.2 and 6.1), and the rows go into `apps/ascend-agent/docs/CONFIGURATION.md` in the same commit as the setting (task 9.7). Made external: the safety bounds of D15 (`APP_INTEGRATIONS_SAFETY_CONTAINER_CPUS` 0.25, `APP_INTEGRATIONS_SAFETY_CONTAINER_MEMORYMIB` 256, `APP_INTEGRATIONS_SAFETY_CONTAINER_PIDS` 128, `APP_INTEGRATIONS_SAFETY_MAXRUNNINGBUILDS` 1, `APP_INTEGRATIONS_SAFETY_BUILD_MAXFILEBYTES` 1MB, `APP_INTEGRATIONS_SAFETY_BUILD_MAXSOURCEBYTES` 5MB, `APP_INTEGRATIONS_SAFETY_BUILD_MAXDEPENDENCYBYTES` 50MB, `APP_INTEGRATIONS_SAFETY_BUILD_COMMANDTIMEOUT` 300s, `APP_INTEGRATIONS_SAFETY_CALLTIMEOUT` 30s), the build allow-list (`pypi.org,files.pythonhosted.org`), the entry refresh interval (60s), the failure rule (5 calls, 5m), the two runner profile names, and the reconcile cron (`* * * * *`) and zone (`Europe/Warsaw`). New setting names of this round, from values D6 and D10 had kept in their text: `app.integrations.safety.build.max-output-bytes` (`64KB`) and `app.integrations.max-result-chars` (`20000`). The runner values this change relies on (archive bounds, images per integration, orphan image age, service limits and maxima, proxy and gateway sizes, the `/tmp` size and the restart tries) are already settings of `add-agent-sandbox`. Kept as constants, and why, are listed under D22. Secrets with no default: the integration secret variables of D11, only in `integration-secrets.env`. No default value of this change is undecided. No test or measurement of this change uses LM Studio as a default: the deterministic spec of task 10.9 calls no model, the AI-run spec of task 10.11 needs a hosted chat provider key and `OPENCODE_API_KEY`, and the integration tests use the shared Mockoon environment as the model provider.

Answer 98.1: no test line in `compose.yaml`, and the deterministic phase reaches the running containers by copy and recreate (`close-agent-test-gaps` D7). The coding spec of `add-coding-agent-delegation` (its task 9.5) and the integration spec of task 10.9 run last in the deterministic phase, the integration spec after the coding spec. Before them the runner is recreated once with `SANDBOX_CODING_IMAGE` set in the shell of that one command (`docker compose up -d --force-recreate ascend-sandbox-runner`), a step `add-coding-agent-delegation` task 9.5 adds. For the integration spec only, this change then copies the runner overlay into the runner and restarts it: `docker compose exec -u root ascend-sandbox-runner mkdir -p /app/config`, `docker compose cp apps/ascend-agent/e2e/overlay/runner-application-e2e.yaml ascend-sandbox-runner:/app/config/application.yaml` and `docker compose restart ascend-sandbox-runner`, with a start check that `docker compose exec ascend-sandbox-runner cat /app/config/application.yaml` prints the overlay as the runner's own user. The runner's config folder is `/app/config`, because `add-agent-sandbox` task 7.1 gives the runner image `WORKDIR /app`, read again from that Dockerfile at implementation time. The end step recreates the runner with nothing set, and the end check prints `docker compose exec ascend-sandbox-runner printenv SANDBOX_CODING_IMAGE` (the shipped coding image or nothing) and checks that `docker compose exec ascend-sandbox-runner ls /app/config/application.yaml` fails because the copied file is gone. Found while applying: the spec's own secrets file step needs one more recreate of the runner, because compose reads `env_file` only when it creates a container, and that recreate starts from the image and drops the copied file. So that step uses the same recreate command with `SANDBOX_CODING_IMAGE` set and repeats the copy and the restart (D23, task 10.9). Its cleanup removes the variable line and leaves the last recreate to the end step, which always runs. This settles the open point of CANON 26.16 and of answer 90 above on the runner overlay and the runner recreate. Left open for the owner: the runner property the overlay sets to let the egress proxy of a service reach the one private host `e2e-scripted-model` is not named in `add-agent-sandbox`, whose egress proxy refuses every private address. The plan writes it neutrally (task 10.8). Changed: D23, tasks 10.8, 10.9 and 10.12.

Answer 98.10: every `ADMIN` of the tenant gets the `auto_disabled` owner notification. D14, task 6.4 and the `integration-runtime` requirement "An integration that keeps failing is disabled automatically" already create one notification per `ADMIN` of the integration's tenant through the offline `ADMIN` lookup of `add-keycloak-login`, in the transaction of the disable. Confirmed, nothing else changes.

## Open Questions

1. Closed (owner decision 65.7 of 2026-10-04): the running time of integration containers is a metric for now (`sandbox.services.seconds`, D18). If billing starts, it follows the sandbox ledger pattern of `add-agent-sandbox`: a ledger request type of its own, one row written when an integration container stops.
2. Closed (owner answer 82.5 of 2026-10-08): there is no `e2e-fake-quotes` container and no host port of its own. The fake quotes service is served by `e2e-scripted-model`, whose admin API Bruno reaches at `http://127.0.0.1:7033` (task 10.8).
