# Add Customer Stack Installer

## Why

The product is sold as one dedicated stack per customer. `harden-cloud-deployment` delivers a manual guide in `docs/DEPLOYMENT.md`: DNS, TLS, `.env` secrets, data stores, smoke checks, all by hand. That works for the first customer and becomes slow and error-prone after that. A mistyped secret or a skipped step becomes a support incident. For the self-hosted license tier the installer is the thing the customer runs.

This change turns the manual guide into a repeatable installer: infrastructure as code, a bootstrap that generates every secret and assembles `.env`, a separate data-store stack, image pulls from the published registry, first-tenant provisioning and a smoke test that fails the install on a broken stack.

## Build order and dependencies

Build order (owner, 2026-10-01): group A, group B, group D, `harden-cloud-deployment`, group C (`add-auth-and-identity`, `add-tenant-isolation`, `add-usage-metering-and-quotas`, `add-audit-and-gdpr-compliance`, `add-tenant-administration`, `add-tenant-policy`), `add-document-connectors`, then this change, then `update-docs-and-architecture`.

This change depends on:

- `harden-cloud-deployment`: the gateway, the loopback port model, the `.env.example` variable set, the production credential guard, the private object store rule and the backup steps.
- `add-auth-and-identity`: the `keycloak` service on its own host address (host port 8180), the realm export `keycloak/realm-ascend-ai.json` imported at Keycloak start with `--import-realm`, and the Keycloak site in `gateway/Caddyfile` with its own host name.
- `add-tenant-administration`: `POST /api/v1/admin/tenants` and the user endpoints, called as `PLATFORM_ADMIN`.
- `add-document-connectors`: its variables in `.env.example`. Connector credentials are customer inputs and are never generated.
- `add-github-actions-pipeline` (already built): `.github/workflows/release.yaml` publishes `lukk17/ascend-ai-<service>` and `ghcr.io/lukk17/ascend-ai-<service>` with tags `v<version>` and `latest`.

## What Changes

- Owner decision step first: the cloud provider and the DNS provider, and the object store product of the data-store stack. The owner decides them later. No Terraform code is written before the decision is recorded in `design.md`.
- Terraform under `deploy/terraform/`: VM (with an NVIDIA GPU, because `ascend-audio-scribe` reserves one in `compose.yaml`), DNS records for `ASCEND_DOMAIN` and the Keycloak host name, a firewall that opens only 80 and 443, and disks for the data-store volumes.
- Data-store stack: Postgres, Redis, Qdrant and an S3-compatible object store are not in `compose.yaml` (they are external prerequisites). The installer provides them as a separate compose project `ascend-datastores` in `deploy/datastores/compose.yaml`, with no published port except loopback, or points at managed services when the decision step chooses them.
- Image distribution: `compose.yaml` image names become environment-driven so the VM pulls released images instead of building. The installer pins each app to a released version.
- Bootstrap (`deploy/bootstrap.sh`, `deploy/bootstrap.ps1`): generates every secret, takes the LLM provider keys and other customer inputs as inputs, writes `.env`, refuses development defaults.
- Model cache: the `hf-cache` named volume is created on the data disk and filled before the stack starts, so the first transcription does not download models.
- First tenant and admin through the product's own admin API.
- Smoke test as a hard gate.
- One entry point: the application stack is always the main `compose.yaml` with no `-f` flag.

## Capabilities

### New Capabilities

- `stack-provisioning`: the owner decision record, Terraform infrastructure, the data-store stack, image distribution from the registry, the secret-generating bootstrap with customer-supplied provider keys, the model cache, first-tenant provisioning, the smoke test and the single compose entry point.

### Modified Capabilities

None as spec deltas. `production-deployment` and the auth and tenant-administration capabilities live in sibling changes that are not archived yet. This change consumes them.

## Impact

- New files: `deploy/README.md`, `deploy/terraform/`, `deploy/datastores/compose.yaml`, `deploy/datastores/.env.example`, `deploy/bootstrap.sh`, `deploy/bootstrap.ps1`, `deploy/smoke-test.sh`, `deploy/smoke-test.ps1`, `deploy/tests/` (bats and Pester tests).
- `compose.yaml` and `compose.ascend-web-hunter.yaml`: the six app `image:` lines become `${ASCEND_IMAGE_REGISTRY:-}ascend-ai-<service>:${<SERVICE>_IMAGE_TAG:-latest}`. Local builds keep today's names.
- `.env.example`: the image variables.
- `docs/DEPLOYMENT.md`: an automated install section.
- No application code changes.

## Relevant Skills

- `/deployment-patterns`
- `/docker-patterns`
- `/bash`
- `/powershell`
- `/security-review`
- `/keycloak-administration`
- `/postgres-patterns`
- `/markdown-writer`
