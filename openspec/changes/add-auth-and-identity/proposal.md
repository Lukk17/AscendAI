## Why

`add-keycloak-login` gives the personal assistant real login: one Keycloak realm `ascend-ai`, the agent as an OAuth2 resource server, the roles `USER` and `ADMIN`, one tenant `default`, the app client, the confidential clients and the service token. It was split out of this change on 2026-10-04 (owner answer 70.2 of 2026-10-04: the personal assistant itself needs real Keycloak login, so basic Keycloak login is personal, not company). Owner rule of 2026-10-04: the personal assistant comes first, nothing personal, web-hunter or base may depend on company work, and company work comes last and only plugs in through extension points with safe defaults.

What a company needs on top of that is this change. A company deployment serves several customers, each a tenant, and the changes built after this one (`add-tenant-isolation`, `add-usage-metering-and-quotas`, `add-audit-and-gdpr-compliance`, `add-tenant-administration`, `add-tenant-policy`) all presuppose a trustworthy tenant on every identity, which the personal change deliberately fixes to `default`.

`docs/architecture/permission-aware-retrieval.md` settles how AscendAI decides which chunks a person may read, and its ownership table assigns six pieces of that mechanism to this change. This version delivers two of them: the principal identifier format with its typed factory, and group membership resolution. Four are deferred with the directory work they belong to, and are listed as such in `design.md`: the directory object id carried alongside the token subject, the Redis principal-set cache and its time to live, the cross-provider identity link with reused-address detection, and the administrator API that corrects a link. Without the two that land, `add-tenant-isolation` has a filter it cannot populate and `add-document-connectors` writes access lists nothing can be matched against.

Groups are Keycloak realm groups. An administrator creates them, puts people in them, and a protocol mapper puts them into the access token. Nothing is imported from a customer's Microsoft or Google directory in this version. When directory groups return, a customer's directory groups relate to Keycloak groups through a mapping the administrator writes (owner decision 65.14 of 2026-10-04).

Corporate single sign-on is optional configuration. A customer's own identity provider is brokered inside the one realm through the generic OpenID Connect provider or SAML, Keycloak Organizations route a person to their customer's provider by email domain, and a person who arrives that way still lands in the Keycloak groups an administrator assigned to them. Brokering changes where a person authenticates. It does not change where their groups come from.

That simplification has one consequence that has to be stated rather than softened. A document synced from SharePoint or Google Drive carries that source's own group identifiers in its access list, and a Keycloak group name will never match one. Per-document permissions therefore work for documents uploaded directly into the product, and match nothing at all for documents synced from a customer's own storage. For this version a connector-synced document is visible to everyone in the company. It is recorded in `design.md` as a named limitation, together with what would have to be built to lift it.

## What Changes

- Plugs into `add-keycloak-login` through its two extension points (its D22), never by editing its classes: a claim-reading `TenantResolver` replaces the default `default` tenant, and an `IdentityContributor` adds the caller's group identifiers and principal set to the resolved identity, on the token path, the dev path and the resolution without a token alike.
- Multi-tenant claims. The realm export gains a protocol mapper emitting the `tenant` user attribute as the `tenant` claim, and a realm user who arrived through no brokered provider carries the tenant `default`. The resolver reads the claim from a token and the attribute from the Keycloak user representation of a resolution without a token, defaulting to `default` when absent. The claim name and default are a stable contract that `add-tenant-isolation` enforces.
- Groups live in Keycloak and nowhere else. The realm export gains realm groups and a group protocol mapper that puts the group names into the access token. Group membership is read from that claim, and for a resolution without a token from Keycloak's admin API with the `ascend-agent-directory` client of `add-keycloak-login`. No directory is called, and no group data is imported from any upstream provider.
- A principal set on every request. A typed factory produces `namespace:type:id` principals from the caller's Keycloak groups. The set is assembled once during authentication, is immutable for the life of the request, and is capped at 256. A caller over the cap gets an error rather than a truncated set. `PrincipalContext.currentPrincipals()` returns it as an `Optional` (owner decision 65.23 of 2026-10-04).
- The dev profile of `add-keycloak-login` gains a usable principal set (`tenant:everyone:default` and `local:group:dev-all`) through the contributor, so a developer running locally against a seeded corpus actually retrieves documents.
- Two roles stay two roles, and roles are not principals. Roles gate endpoints, principals gate documents, and an `ADMIN` token widens the endpoint matrix while widening retrieval by nothing at all.
- Identity brokering is optional configuration for a customer who wants corporate sign-on. One brokered identity provider per customer inside the one realm, configured through the generic OpenID Connect provider pointed at the customer's discovery document or through SAML (configuration only, owner decision 65.16 of 2026-10-04), never code. The brokered provider stamps the `tenant` value onto everyone who arrives through it. A person who arrives through it is a realm user like any other, and their groups are the Keycloak groups an administrator assigned. No group claim, and no other attribute carrying authorization meaning, is imported across the broker.
- Keycloak Organizations route a person to their customer's brokered provider by email domain (owner decision 65.15 of 2026-10-04), and a person whose domain matches nothing is never dropped into a default provider.
- Directory groups and their mapping stay deferred, with their analysis intact. When they return, an administrator maps a directory group to a Keycloak group of the tenant (owner decision 65.14 of 2026-10-04).
- A named limitation, recorded rather than worked around. No principal this version can mint matches a directory group identifier, so an access list naming one matches nobody. Connector-synced documents are company-visible for this version.
- Test tenants for company specs in the development overlay: `e2e-acme`, `e2e-globex` and `e2e-soul`, with their users, the group user `e2e-finance-acme` and the stand-in customer realm `e2e-customer` for brokered sign-in. A deterministic spec for brokered sign-in. Tenant claims and group principals are proved by integration tests and get no end-to-end spec (owner answer 91.3 of 2026-10-08).

## Capabilities

### New Capabilities

- `identity-brokering`: optional corporate single sign-on, one brokered identity provider per customer inside the realm of `add-keycloak-login`, configured through the generic OpenID Connect provider or SAML, the Keycloak Organizations routing by email domain, the tenant stamp, and the rule that a brokered person's authorization comes from Keycloak groups rather than from anything the upstream token asserted.
- `principal-resolution`: the `namespace:type:id` principal format and its typed factory, group membership resolved from the Keycloak group claim, the immutable capped principal set the search filter is later composed from, the dev principal set, and the stated fact that a directory group identifier matches nothing in this version.

Three capabilities are shared with `add-keycloak-login`, which adds their first requirements and lands first. This change adds further requirements to them, with names of their own:

- `user-identity`: the tenant read from the `tenant` claim through the replaced `TenantResolver`, the principal set carried in the identity extensions, and roles never widening retrieval.
- `identity-provider`: Keycloak realm groups and their mapper, the `tenant` mapper and attribute, and the test tenants of the development overlay.
- `agent-authentication`: the company end-to-end spec (brokered sign-in, test tenants).

### Modified Capabilities

(none. No capability under `openspec/specs/` changes, because `add-keycloak-login` is not archived yet.)

## Impact

- ascend-ai-agent: a claim-reading `TenantResolver` bean and a principal `IdentityContributor` bean, the principal factory and value type, the membership resolver reading the Keycloak group claim and, without a token, the user's groups through Keycloak's admin API, `PrincipalContext`, `app.identity.*` configuration binding the group claim name and the principal cap. No class of `add-keycloak-login` is edited.
- Keycloak realm export of `add-keycloak-login`: the `tenant` and group protocol mappers, realm groups, a disabled brokered-provider template entry and the organization template. Development overlay: the test tenants and their users, and the stand-in customer realm.
- Operations: the group administration runbook, the optional brokering and Organizations runbook, the SAML steps and the named limitation, all in `docs/SECURITY.md`.
- `docs/architecture/`: `permission-aware-retrieval.md` and `ADR-M007` describe a membership order and an ownership table that this version only partly delivers. Both need an amendment naming what this version does and what it defers. That edit is a task in this change.
- Blocks: `add-tenant-isolation` cannot compose an access-list predicate without the principal set and the tenant claim, and `add-document-connectors` cannot write access lists without the principal format. The tasks those two changes wait on are marked in `tasks.md`.
- Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 5 (company), position 1. It needs `add-keycloak-login` (build group 3, position 3), and it lands after every web-hunter, base and personal change. `add-tenant-isolation`, `add-tenant-policy`, `add-tenant-administration`, `add-audit-and-gdpr-compliance`, `add-usage-metering-and-quotas`, `add-document-connectors` and `add-customer-stack-installer` plug into it later. The company order of 2026-10-01 (`harden-cloud-deployment`, then this change, then the other company changes) is superseded by the owner build order of 2026-10-04. It ships no schema change, and the deferred `identity_link` table, if it returns, is a Flyway versioned SQL migration.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/keycloak-administration`
- `/keycloak-auth-services`
- `/api-design`
- `/tdd-workflow`
- `/security-review`
- `/e2e-runbooks`
