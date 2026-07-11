# Tasks — add-customer-stack-installer

## 1. Terraform infrastructure

- [ ] 1.1 Create `deploy/terraform/` provisioning a VM, the DNS record for `ASCEND_DOMAIN`, a firewall opening only 80/443, and data-store volumes/backup; keep the cloud provider a module variable
- [ ] 1.2 Parameterize VM size, region, domain, and provider credentials via Terraform variables; document state handling in `deploy/README.md`
- [ ] 1.3 Verify: `terraform plan` on the first target provider renders cleanly; `terraform apply` produces a VM reachable on 80/443 only

## 2. Secret-generating bootstrap

- [ ] 2.1 Create `deploy/bootstrap.sh` and `deploy/bootstrap.ps1`: read the `.env.example` variable set (`harden-cloud-deployment`), generate strong values for every secret, assemble a complete `.env`
- [ ] 2.2 Abort with a clear message if any required secret is missing or blank; never emit a dev-default value
- [ ] 2.3 Document where the generated `.env` is stored and how to rotate a secret
- [ ] 2.4 Test: a dry run produces a `.env` with every required variable set and no dev-default; a forced-blank required secret aborts the run

## 3. Realm import and first-tenant provisioning

- [ ] 3.1 Import the checked-in Keycloak realm export (`add-auth-and-identity`) into the running Keycloak
- [ ] 3.2 Create the customer's first tenant and its initial `ADMIN` user via the `add-tenant-administration` API as `PLATFORM_ADMIN`; retry against a health check until Keycloak/agent are ready
- [ ] 3.3 Test: after provisioning, the seeded admin can acquire a token and the tenant exists

## 4. Readiness smoke test

- [ ] 4.1 Create `deploy/smoke-test.sh` and `deploy/smoke-test.ps1`: verify gateway TLS, AscendAgent health behind the gateway, token acquisition for the seeded admin, and one authenticated round-trip
- [ ] 4.2 Exit non-zero and name the failing check on any failure; the installer treats this as a hard gate
- [ ] 4.3 Test: the smoke test passes on a healthy stack and fails visibly when the gateway or agent is down

## 5. Orchestration over the single compose file

- [ ] 5.1 The installer runs `docker compose up` against the main `docker-compose.yaml` with no `-f` flags (owner constraint); ordered infra → bootstrap → compose up → realm/tenant → smoke test
- [ ] 5.2 End-to-end rehearsal on a throwaway target: infra provisioned, secrets generated, stack healthy, first tenant/admin usable, smoke test green

## 6. Documentation

- [ ] 6.1 Add an "automated install" section to `docs/DEPLOYMENT.md` pointing at the installer as the primary path, keeping the manual runbook as the documented fallback
- [ ] 6.2 Write `deploy/README.md`: prerequisites, provider setup, run order, secret storage/rotation, teardown
