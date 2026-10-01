# Tasks - Add Customer Stack Installer

Build order: after `harden-cloud-deployment`, group C and `add-document-connectors`, before `update-docs-and-architecture`. Load the skills in the proposal's Relevant Skills section first. The application stack is always started with the main `compose.yaml` and no `-f` flag.

## 0. Owner decision (blocks everything below)

- [ ] 0.1 Ask the owner for the cloud provider (with the GPU VM type and region), the DNS provider, and the object store product for the data-store stack (design D0). Record the answers in the "Recorded decisions" section of `openspec/changes/add-customer-stack-installer/design.md`. Acceptance: the section names all three and the owner has confirmed them in the conversation.

## 1. Image distribution

- [ ] 1.1 In `compose.yaml` and `compose.ascend-web-hunter.yaml`, change the six app `image:` lines (ascend-ocr, ascend-agent, ascend-memory, ascend-weather-mcp, ascend-audio-scribe, ascend-web-hunter) to `${ASCEND_IMAGE_REGISTRY:-}ascend-ai-<service>:${<SERVICE>_IMAGE_TAG:-latest}` (design D3). Acceptance: with the variables unset, `docker compose config --images` lists the same names as before the change.
- [ ] 1.2 Add `ASCEND_IMAGE_REGISTRY` and the six tag variables to `.env.example` with one comment line each. Acceptance: `grep -c '_IMAGE_TAG=' .env.example` prints 6.
- [ ] 1.3 Verify: with `ASCEND_IMAGE_REGISTRY=ghcr.io/lukk17/` and `ASCEND_AGENT_IMAGE_TAG` set to a released `v<version>`, `docker compose pull ascend-agent` pulls that image.

## 2. Terraform infrastructure

- [ ] 2.1 Create `deploy/terraform/` with a root module and `deploy/terraform/modules/<provider>/` for the recorded provider (design D1): VM with an NVIDIA GPU, data disk, firewall (80 and 443 open, 22 from an operator address list), DNS records for `ascend_domain` and `keycloak_domain` at the recorded DNS provider. Acceptance: `terraform -chdir=deploy/terraform validate` exits 0.
- [ ] 2.2 Variables for credentials (environment only), region, VM type, domains, SSH key, disk size, and outputs for public IP and SSH user. Acceptance: `terraform -chdir=deploy/terraform plan` with example variables renders without errors.
- [ ] 2.3 Verify on a throwaway account: `terraform apply` produces a VM whose public IP answers only on 80, 443 and 22 (from the allowed address), checked with `nmap -Pn <ip>`, and both DNS names resolve to it. Destroy afterwards with `terraform destroy`.

## 3. Data-store stack

- [ ] 3.1 Create `deploy/datastores/compose.yaml`, project `ascend-datastores` (design D2): Postgres with databases `ascend_ai` and `keycloak`, Redis with `requirepass`, Qdrant with an API key, and the S3-compatible store when D0 chose a container. Every image pinned by version and digest, every port bound to `127.0.0.1`, data on named volumes, healthchecks, `restart: unless-stopped`. Acceptance: `docker compose -f deploy/datastores/compose.yaml config --quiet` exits 0.
- [ ] 3.2 Create `deploy/datastores/.env.example` listing every variable of that file with empty secret values. Acceptance: every `${VAR` in `deploy/datastores/compose.yaml` appears in it.
- [ ] 3.3 Verify: `docker compose -f deploy/datastores/compose.yaml up -d` reports every service healthy, and the application stack started afterwards reaches all four through `host.docker.internal` (agent `/actuator/health` shows `db`, `redis` and the Qdrant check `UP`).
- [ ] 3.4 Document backup and restore of the data-store volumes in `deploy/README.md`, reusing the per-store commands from the `docs/DEPLOYMENT.md` section `harden-cloud-deployment` wrote rather than repeating them. Acceptance: the README links that section and adds only the volume and disk steps.

## 4. Bootstrap

- [ ] 4.1 Create `deploy/bootstrap.sh` and `deploy/bootstrap.ps1` with the three variable lists of design D4. Write the tests first: `deploy/tests/bootstrap.bats` and `deploy/tests/bootstrap.Tests.ps1`. Acceptance: a test asserts that the union of the three lists equals the variable set of `.env.example`.
- [ ] 4.2 Generate every value in the generated list from the system random source, read customer inputs from the environment or a prompt, require at least one LLM provider key, set `MEM0_DEFAULT_PROVIDER` from it, and write fixed production values. Acceptance: a test run produces a `.env` where every required variable is set and none equals a development default (`admin`, `password`, `local`, empty).
- [ ] 4.3 Abort before writing when a required value is blank or a development default, naming the variable. Refuse to overwrite `.env` without `--rotate`. Write `.env` with mode 600. Acceptance: tests cover the blank case, the default case, the overwrite case and the file mode.
- [ ] 4.4 Pass `bash -n`, `shellcheck deploy/*.sh` and `Invoke-ScriptAnalyzer deploy/*.ps1` with no finding. Acceptance: all three commands report nothing.

## 5. Model cache and GPU

- [ ] 5.1 In the installer, check for the NVIDIA container runtime (`docker info --format '{{json .Runtimes}}'` contains `nvidia`) and fail with a clear message when it is missing. Acceptance: on a host without it the installer stops before `docker compose up` and names the missing runtime.
- [ ] 5.2 Fill the `hf-cache` named volume before the stack starts by running the ascend-audio-scribe image once with the volume mounted to download the configured Whisper model (design D5). Acceptance: `docker run --rm -v hf-cache:/hf-cache alpine du -sh /hf-cache` shows the model, and the first transcription request logs no model download.

## 6. Start the stack, first tenant and admin

- [ ] 6.1 Order: data-store stack up and healthy, `docker compose pull` the six apps, `docker compose up -d --no-build` for the pulled services and `docker compose up -d --build container-metrics-exporter`, then wait until every service reports healthy. Acceptance: `docker compose ps` shows every service `healthy` and `docker compose ls` shows only `ascend-ai` and `ascend-datastores`.
- [ ] 6.2 Wait for Keycloak's health endpoint, confirm the `ascend-ai` realm exists (imported at start by `add-auth-and-identity`), get a `PLATFORM_ADMIN` token as `add-tenant-administration` documents, call `POST /api/v1/admin/tenants` and create the first `ADMIN` user through that change's user endpoint (design D6). Acceptance: `GET /api/v1/admin/users` with the platform token lists the new admin in the new tenant.
- [ ] 6.3 Print the admin sign-in address and a one-time password, never write it to a log file. Acceptance: the installer log on disk contains no password, checked with `grep`.

## 7. Smoke test

- [ ] 7.1 Create `deploy/smoke-test.sh` and `deploy/smoke-test.ps1` with the checks of design D7, exiting non-zero and naming the first failed check. Acceptance: passes on a healthy stack.
- [ ] 7.2 Acceptance: with `docker compose stop ascend-agent` the smoke test exits non-zero naming the health check, and the installer reports the install as failed.

## 8. Documentation and rehearsal

- [ ] 8.1 Write `deploy/README.md`: prerequisites, recorded provider choices, run order, secret storage and rotation, data-store backup, teardown. Follow `/markdown-writer`. Acceptance: every command is in its own code block with a PowerShell and a Unix-shell form where they differ.
- [ ] 8.2 Add an automated install section to `docs/DEPLOYMENT.md` that points to the installer as the main path and keeps the manual steps as the fallback. Acceptance: the section links `deploy/README.md`.
- [ ] 8.3 Full rehearsal on a throwaway account from an empty directory: Terraform, data stores, bootstrap, stack, first tenant, smoke test green, then `terraform destroy`. Acceptance: the run log shows every phase completed and the smoke test exit code 0.
