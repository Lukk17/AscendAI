# Design - Add Customer Stack Installer

## Context

After `harden-cloud-deployment`, group C and `add-document-connectors`, the pieces of a customer stack exist: the main `compose.yaml` with a gateway on 80 and 443, Keycloak on its own host name, the admin API, and a manual guide. Nothing strings them into a repeatable install. The four data stores are external prerequisites that `compose.yaml` does not define, and the VM must pull released images instead of building from source.

## Goals / Non-Goals

Goals:

- One command per phase: decide and provision infrastructure, start data stores, bootstrap `.env`, pull and start the stack, provision the first tenant, verify.
- No hand-typed generated secret and no development default in production.
- A broken install fails visibly.

Non-Goals:

- A shared multi-tenant control plane or an onboarding web page.
- Application code changes.
- Choosing the cloud provider, DNS provider or object store product in this design. That is the owner's decision step D0.

## Decisions

### D0 - Owner decision step, before any code

The owner decides three things and records them in a "Recorded decisions" section at the end of this file:

1. Cloud provider (and with it the VM type with an NVIDIA GPU and the region).
2. DNS provider.
3. Object store for the data-store stack: the provider's managed S3-compatible storage, or an S3-compatible container in `deploy/datastores/compose.yaml`.

Every other task waits for this record. The implementer asks the owner and does not pick.

### D1 - Terraform, provider in its own module

`deploy/terraform/` has a root module and one provider module named after the recorded provider (`deploy/terraform/modules/<provider>/`). Inputs: provider credentials (from the environment, never a file in the repo), region, VM type, `ascend_domain`, `keycloak_domain`, SSH public key, data disk size. Outputs: VM public IP, SSH user. The firewall allows inbound 80 and 443 from anywhere and 22 only from an operator address list. State is local by default with a documented remote-backend option. A second provider later is a new module.

### D2 - Data stores come from a separate stack

`compose.yaml` keeps no data store (owner rule). On the VM the installer runs `deploy/datastores/compose.yaml`, project name `ascend-datastores`, with Postgres (databases `ascend_ai` and `keycloak`), Redis with a password, Qdrant with an API key, and the S3-compatible store when D0 chose a container. Each service binds only `127.0.0.1` and stores data on named volumes on the Terraform data disk. The application stack reaches them through `host.docker.internal`, like the local-dev stack does today. When D0 chose managed services, this file runs without the object store service and `.env` points at the managed address. This is a prerequisite stack, not a second application project, so the single entry point rule for the application stack holds.

### D3 - Images from the registry

`release.yaml` publishes `lukk17/ascend-ai-<service>` and `ghcr.io/lukk17/ascend-ai-<service>`. The six app `image:` lines in the compose files become `${ASCEND_IMAGE_REGISTRY:-}ascend-ai-<service>:${<SERVICE>_IMAGE_TAG:-latest}`, for example `${ASCEND_IMAGE_REGISTRY:-}ascend-ai-ascend-agent:${ASCEND_AGENT_IMAGE_TAG:-latest}`. Unset, the names equal today's local build names, so local `docker compose up --build` is unchanged. The installer sets `ASCEND_IMAGE_REGISTRY=ghcr.io/lukk17/` and each tag to the released `v<version>`, runs `docker compose pull` for the six services, then `docker compose up -d --no-build` for them. `container-metrics-exporter` is not released and is built on the VM from the repo checkout.

### D4 - Bootstrap: generate secrets, ask for inputs

`deploy/bootstrap.sh` and `deploy/bootstrap.ps1` read `.env.example` and sort every variable into one of three lists kept at the top of each script, one list per class, which a test checks against `.env.example` so a new variable cannot be missed:

- Generated: every password, secret key and API key the stack owns (Postgres, Redis, Qdrant, object store keys, ascend-ocr result store keys, `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET` at 48 characters, `VNC_PASSWORD`, `SECURITY_PASSWORD`, Keycloak admin password). Values come from the system random source (`openssl rand` or `[System.Security.Cryptography.RandomNumberGenerator]`).
- Customer inputs: LLM provider keys (`OPENAI_API_KEY`, `ASCEND_ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`), `HF_TOKEN`, connector credentials, `ASCEND_DOMAIN`, the Keycloak host name. Read from the environment or a prompt. At least one LLM provider key is required, because a customer VM has no LM Studio. `MEM0_DEFAULT_PROVIDER` is set to the provider of the first key given.
- Fixed production values: `EXPOSE_BIND=127.0.0.1`, `SPRING_PROFILES_ACTIVE=docker,production`, both public object store endpoints equal to the private address, `MCP_ALLOWED_HOSTS` set to the object store host only, image registry and tags.

The script writes `.env` with mode 600, refuses to overwrite an existing `.env` without `--rotate`, and aborts before writing when any required value is blank or equals a development default.

### D5 - Model cache

`HF_CACHE_ROOT` stays the `hf-cache` named volume from `harden-cloud-deployment`. Before the stack starts the installer runs the ascend-audio-scribe image once with the volume mounted and downloads the configured Whisper model, so the first request is not a download. The installer checks for the NVIDIA container runtime first and fails with a clear message when it is missing.

### D6 - First tenant through the product API

The realm is imported by Keycloak itself at start (`--import-realm`, from `add-auth-and-identity`). The installer waits for the Keycloak health endpoint, gets a `PLATFORM_ADMIN` token the way `add-tenant-administration` documents for the platform operator, calls `POST /api/v1/admin/tenants`, then creates the tenant's first `ADMIN` user through the user endpoint that change defines. The implementer reads `openspec/specs/` (or the change folder if not archived) of `add-tenant-administration` for the exact request bodies.

### D7 - Smoke test is a hard gate

`deploy/smoke-test.sh` and `.ps1` check, in order: gateway TLS certificate valid for `ASCEND_DOMAIN`, `GET https://<ASCEND_DOMAIN>/actuator/health` returns 200, Keycloak's discovery document answers on its own host name, a token for the seeded admin is issued, one authenticated `POST /api/v1/ai/prompt` returns 200, and an external port scan from the operator machine shows only 80 and 443. The script exits non-zero naming the first failed check.

### D8 - One application entry point

The installer starts the application stack only with `docker compose` against the main `compose.yaml`, no `-f` flag. The data-store stack is the one other project, as in D2.

## Risks / Trade-offs

- GPU VMs cost more. The decision is the owner's in D0. A later change may make ascend-audio-scribe optional.
- Local Terraform state can be lost. `deploy/README.md` documents the remote-backend option.
- Generated `.env` on the VM holds every secret. Mode 600, never committed, rotation documented.
- The bootstrap variable lists can drift from `.env.example`. A test compares them.

## Open Questions

- D0: cloud provider, DNS provider, object store product. Owner decision, recorded below before implementation.

## Recorded decisions

Empty until the owner decides D0.
