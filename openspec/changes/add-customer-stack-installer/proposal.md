## Why

The go-to-market is single-tenant-per-customer dedicated stacks, and `harden-cloud-deployment` delivers only a manual deployment guide: DNS, TLS, `.env` secret generation, Keycloak realm import, and a smoke test done by hand. That is fine for the first customer and a margin killer by the third. Onboarding by hand is slow, error-prone (a mistyped secret or a skipped step is a support incident), and unrepeatable. For the self-hosted license tier the installer effectively is the product — the thing the customer runs.

This change turns the manual guide into a scripted, repeatable installer: infrastructure as code plus a bootstrap that generates every secret, assembles `.env`, imports the realm, brings the stack up, and verifies it. It is deliberately last: it automates a deployment posture the other changes must define first.

## What Changes

- **Infrastructure as code (Terraform)**: a Terraform configuration that provisions a cloud VM, its DNS record for `ASCEND_DOMAIN`, firewall rules opening only 80/443 (the gateway's ports from `harden-cloud-deployment`), and the volumes/backups for the four data stores. Cloud-provider module boundaries kept clean so the target provider is a variable, not a rewrite.
- **Bootstrap script**: a script (PowerShell and Bash variants) that generates strong values for every secret in `.env.example` (`harden-cloud-deployment` owns the variable list), assembles a complete `.env`, and refuses to proceed if any required secret is unset — no dev-default ever reaches production.
- **Realm and first-tenant provisioning**: import the checked-in Keycloak realm export (`add-auth-and-identity`), then create the customer's first tenant and its initial `ADMIN` user through the tenant-administration API (`add-tenant-administration`), so a fresh stack lands with a usable admin account, not an empty Keycloak.
- **Readiness smoke test**: a scripted check that the gateway serves TLS, AscendAgent is healthy behind it, a token can be acquired, and one authenticated request succeeds — the install fails loudly if any of these do not pass, rather than handing over a silently-broken stack.
- **One entry point**: the installer drives the existing main `docker-compose.yaml` (no `-f` files, the hard owner constraint), so the installed stack is byte-identical to a hand-brought-up one, just automated.

## Capabilities

### New Capabilities

- `stack-provisioning`: Terraform infrastructure (VM, DNS, gateway-only firewall, data-store volumes/backup) with a provider variable; the secret-generating bootstrap that assembles a complete production `.env` and fails on any unset required secret; realm import plus first-tenant/admin provisioning; and a readiness smoke test that fails the install on a broken stack — all driving the single main `docker-compose.yaml`.

### Modified Capabilities

(none as spec deltas — `production-deployment` and the auth/tenant-admin capabilities live in sibling changes not yet archived to `openspec/specs/`. This change is additive automation on top of them; the variables, realm export, and admin API it consumes are named in the tasks for coordination.)

## Impact

- **Depends on**: `harden-cloud-deployment` (gateway, `.env.example` variable set, secrets fail-fast, backup procedures), `add-auth-and-identity` (realm export to import), `add-tenant-administration` (first-tenant + admin provisioning API). Ideally all archived first; this is the last functional change.
- **New files**: `deploy/terraform/` (provider-parameterized VM/DNS/firewall/volumes), `deploy/bootstrap.sh` + `deploy/bootstrap.ps1` (secret generation, `.env` assembly, realm import, first-tenant provisioning), `deploy/smoke-test.sh` + `deploy/smoke-test.ps1` (readiness checks). No application code changes.
- **Docs**: `docs/DEPLOYMENT.md` (from `harden-cloud-deployment`) gains an "automated install" section pointing at the installer; a `deploy/README.md` with the run-book.
- **Secrets**: the bootstrap generates values; nothing is committed; the installer documents where generated secrets are stored/rotated.
- **Tests / verification**: a dry-run of the bootstrap on a throwaway target produces a valid `.env` and a healthy stack that passes the smoke test; the bootstrap aborts when a required secret cannot be generated or is left blank.

## Relevant Skills

- `/deployment-patterns`
- `/docker-patterns`
- `/bash`
- `/powershell`
- `/security-review`
