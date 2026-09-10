# Design — add-customer-stack-installer

## Context

`harden-cloud-deployment` makes the main `compose.yaml` the single entry point, puts a gateway on 80/443, moves every secret into `.env`, and fails fast on an unset secret in the production posture — but the actual VM, DNS, TLS, secret generation, realm import, and verification are a manual runbook. `add-auth-and-identity` ships a checked-in realm export; `add-tenant-administration` provides the API to create the first tenant and admin. The pieces exist; nothing strings them into a repeatable install.

## Goals / Non-Goals

**Goals:**

- One command per phase to stand up a dedicated customer stack: provision infra, bootstrap secrets + config, import realm + first tenant, verify.
- Zero hand-typed secrets; zero dev-defaults reaching production.
- Provider-agnostic infra (target cloud is a variable).
- A hard readiness gate: a broken install fails visibly.

**Non-Goals:**

- Multi-tenant control-plane provisioning (dedicated single-tenant stacks are the target).
- A hosted control panel / SaaS onboarding UI.
- Application code changes — this is pure automation over the existing compose stack.
- Managed-service wiring beyond what `harden-cloud-deployment` already documents (the installer references it, does not re-specify it).

## Decisions

### D1 — Terraform for infra, provider as a variable

Terraform provisions the VM, the DNS record for `ASCEND_DOMAIN`, a firewall that opens only 80/443, and the data-store volumes/backup. The cloud provider is a module boundary/variable so a second target is a new module, not a rewrite. Terraform state handling and the chosen provider are documented in `deploy/README.md`.

### D2 — Bootstrap script generates every secret and assembles `.env`

A cross-platform bootstrap (Bash + PowerShell) reads the `.env.example` variable list (owned by `harden-cloud-deployment`), generates strong values for each secret, writes a complete `.env`, and aborts if any required secret is missing or blank. This is the single source of secret generation, so the "no dev-default in production" guarantee is enforced by the tool, not by discipline.

### D3 — Realm import then first-tenant provisioning via the API

After the stack is up, the installer imports the Keycloak realm export, then calls the `add-tenant-administration` API (as `PLATFORM_ADMIN`) to create the customer's first tenant and its initial `ADMIN` user, so the customer receives working credentials rather than an empty realm. This reuses the product's own provisioning path instead of duplicating Keycloak scripting.

### D4 — Readiness smoke test is a hard gate

A scripted check verifies: the gateway serves TLS, ascend-ai-agent is healthy behind it, a token can be acquired for the seeded admin, and one authenticated request round-trips. The installer exits non-zero and reports which check failed if any does, so a broken stack is never silently handed over.

### D5 — Drive the single main compose file

The installer runs the existing `docker compose up` against the main `compose.yaml` with no `-f` flags, so an installed stack is identical to a hand-brought-up one. This preserves the owner's hard constraint that the main compose file is the only entry point.

## Risks / Trade-offs

- [Terraform provider lock-in] → provider is a module variable; the first target is implemented, others are additive.
- [Secret storage after generation] → the bootstrap documents where the generated `.env` lives and how to rotate; secrets are never committed.
- [Realm/first-tenant step runs before the stack is ready] → the installer orders provisioning after the readiness gate for the gateway/agent, and the tenant call retries against a health check.
- [Installer drifts from the manual runbook] → `docs/DEPLOYMENT.md` points at the installer as the primary path and keeps the manual steps as the documented fallback, one source each.

## Open Questions

- None blocking. The first concrete cloud provider target is an implementation choice; the module boundary keeps it swappable.
