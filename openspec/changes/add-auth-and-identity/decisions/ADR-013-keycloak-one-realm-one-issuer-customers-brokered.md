# ADR-013: Keycloak Is the Identity Layer, With One Realm, One Issuer, and One Brokered Provider Per Customer

## Status

Proposed, 2026-09-04. Amended 2026-09-04, see Amendment below. Accepted when the OpenSpec change `add-auth-and-identity` lands. This file is the draft that task 12.8 installs into `apps/ascend-ai-agent/docs/architecture/decisions/`, taking the next free number at that time.

## Amendment, 2026-09-04

The decision below stands. Keycloak is the identity layer, there is one realm, there is one issuer, and a customer is a tenant value inside it. Three parts of its scope narrowed on the same day it was written, and the narrowing is recorded here rather than by editing the body, so the reasoning that produced the original stays readable.

Password sign-in is the default. A person has a Keycloak account and types their password on Keycloak's own login page, and the application receives an authorization code. The body below reads as though brokering were the normal way a person arrives. It is not. It is optional configuration for a customer who wants corporate single sign-on, and nothing on the password path depends on it existing.

The distinction that must not be lost while reading the previous paragraph: password sign-in means the authorization code flow against Keycloak's login page, and it is not the direct access grant. The direct access grant, in which the application itself collects the password, stays disabled on every client a customer touches. It survives only on the development overlay's own client so the test suites can obtain a token without a browser. Enabling password sign-in never means enabling that grant.

Brokering no longer carries authorization. Group identifiers are not imported across the broker, and a person who arrives through a brokered provider is a realm user like any other whose groups are the Keycloak realm groups an administrator assigned. The brokered provider still stamps the tenant, still cannot override it from an upstream claim, and still cannot mint a platform role. Everything the body says about the tenant stamp holds. Everything it implies about a customer's directory supplying group membership is deferred, and the records that carried that work say so on their own Status lines.

The realm export contract in the body changes with it. The user profile declarations existed for attributes a brokered provider imports, and with nothing imported there is nothing to declare, so they leave the export along with the group Attribute Importer on the template entry. Two things join it: realm groups with the protocol mapper that emits them, which are now the only source of group principals, and a realm password policy, because password sign-in is the default path and the policy that protects it belongs in the provisioning rather than in an operator's memory. The roles, the PKCE client with direct access grants off, the session and token lifetimes, and the disabled brokered-provider template all stay exactly as the body describes them.

The consequence of that narrowing is a named limitation rather than a silent one. No principal this version mints matches a group identifier from an external directory, so an access list captured from a customer's own storage matches nobody. Documents synced from a customer's storage are visible tenant-wide for this version, and per-document permissions apply to documents uploaded directly into the product. The change's design document carries the full statement and what would have to be built to lift it.

## Context

`add-auth-and-identity` was written with Keycloak as a development convenience. The agent would validate tokens from a local realm so that work could proceed, and a real identity provider would replace it later by repointing `issuer-uri`. Every claim about portability in that change rested on that assumption, and so did the shape of the realm export, which was a fixture rather than a deployment artifact.

The platform decision has been taken and it is different. Keycloak, self-hosted, is the identity layer in production. Customers do not bring their own issuer. Keycloak brokers a customer's identity provider as configuration rather than as code: one entry per customer, created as the generic OpenID Connect provider pointed at the customer's own discovery document, or the SAML provider where that is all the customer offers. There is no Microsoft-specific provider type to reach for and none is needed. That is the reason the product was chosen, because it turns an integration per customer into a form per customer.

Two structural questions follow immediately and neither has an obvious answer. Does a multi-customer deployment need one realm or one realm per customer, and therefore one token issuer or many? And which of the two, the token issuer or the brokered provider, identifies a customer for the purposes of the tenant claim, the principal namespace, and the directory adapter?

The sibling changes make the first question expensive to leave open. `add-tenant-isolation`, `add-usage-metering-and-quotas`, and `add-audit-and-gdpr-compliance` were all designed against a single issuer. If a multi-customer deployment needs an issuer per customer, every one of them needs an issuer registry, a resolution step in front of token validation, and a migration.

## Decision

Keycloak is the platform's identity provider in every posture, development and production alike. One realm, `ascend-ai`, is the only issuer ascend-ai-agent validates against, and it serves every customer.

A customer is a brokered identity provider inside that realm. The provider's alias is the customer's identifier, and three things hang off it: a hardcoded-attribute mapper stamping the customer's `tenant` value onto everyone who arrives through it, the principal namespace their groups mint into, and the directory adapter that answers membership for them.

The single-issuer assumption in the sibling changes therefore survives intact and needs no rework. There is no issuer registry, no per-request issuer resolution ahead of validation, and no more than one configured `issuer-uri`. Tenant separation is carried by the `tenant` claim and by the search filter `add-tenant-isolation` composes, which is where it was already carried.

The realm export stops being a test fixture and becomes the provisioning of a real system. What it must contain is a contract: the roles with `USER` as the realm default, the application client with PKCE and direct access grants disabled, the protocol mappers the claims contract depends on, a declarative user profile declaration for every attribute a brokered provider imports, explicit session and token lifetimes because they bound membership staleness on the claim path, and a disabled brokered-provider template carrying the known-good mapper set. The seeded human user and the password-grant client the test suites need move into a development overlay that a production deployment does not import.

## Consequences

### Why this way

- One issuer is strictly simpler than many and it costs nothing that the tenant claim was not already paying for. A realm boundary would give blast-radius isolation on realm configuration and per-customer session lifetimes, and would charge an issuer registry, N JWKS caches, a resolution step before token validation, and a migration in three sibling changes for it.
- Onboarding becomes an administrative procedure rather than a release. That is the whole value of the product being brokered rather than integrated, and it only holds if the brokered provider, not the issuer, is what identifies a customer.
- `sub` becomes more stable rather than less. It is now Keycloak's own subject for a realm user, so a customer changing which provider they broker keeps their people's chat history and semantic memory as long as the federated link is preserved. Validating provider tokens directly would have re-keyed everybody on every such change.
- A customer's directory can no longer mint a platform administrator. Roles are realm roles assigned on our side, `USER` is the realm default, and no role mapper reads a customer's group claim.
- The export as a contract makes a clean rebuild deterministic and makes a console edit visibly wrong. A fixture can drift from production. A provisioning artifact that is also what production imports cannot.

### Trade-offs

- Keycloak is now a service the platform operates, and if it is down nobody signs in at any customer. It needs a database, certificates, backups with a restore that has actually been run, and an upgrade habit. There is no long-term support release upstream, minor releases land roughly quarterly and patches roughly monthly, breaking changes have shipped inside patch releases, and sixteen security advisories were published this year through August. This is the standing cost of the decision. It is recorded rather than mitigated, because the available mitigations reduce the risk of an upgrade and do not remove the work.
- One realm means one configuration blast radius. A mistake in the realm's user profile, its default roles, or its session lifetimes reaches every customer at once. The export being checked in, reviewed, and rebuilt deterministically is the control, and it is a weaker control than separate realms would have been.
- The tenant claim is now load-bearing in a way it was not when it emitted the constant `default`. A brokered provider with no hardcoded-attribute mapper produces people with the wrong tenant rather than people with no tenant, which is a worse failure than the one it replaces. The onboarding verification exists to catch it.
- Brokering means ascend-ai-agent never sees the upstream provider's token. Anything not deliberately copied across by a mapper is unavailable to it, and ADR-015 is the whole discipline that follows from that.

### Alternatives considered

- One realm per customer, one issuer per customer. Pro: strong configuration isolation, per-customer session policy, and a customer's realm can be exported and handed over. Con: an issuer registry and a resolution step ahead of token validation, N JWKS caches, and rework in three sibling changes that currently assume one issuer, in exchange for isolation the tenant claim already provides. Rejected.
- No broker: register each customer's provider directly as the resource server's issuer and route by issuer. Pro: one fewer moving part, no Keycloak to operate. Con: it is the integration-per-customer model the platform decision exists to avoid, it re-keys `sub` per provider, it puts every provider's quirks into our code, and it is the multi-issuer registry above with extra steps. Rejected.
- Keep Keycloak as a development convenience and defer the production choice. Pro: no operational commitment yet. Con: the realm export, the claims contract, the tenant source, and the membership path all differ between the two worlds, so deferring the decision means building both or building the wrong one. Rejected, because this change cannot freeze a contract for two blocked siblings while leaving the identity layer undecided.
- A vendor-branded Keycloak provider type per customer where one exists. Pro: fewer fields to fill in during an onboarding. Con: there is no Entra-specific provider, the generic OpenID Connect entry pointed at the customer's discovery document is the mechanism, and reaching for a branded type because the logo is familiar produces a configuration the runbook does not describe. Rejected explicitly so it is not rediscovered during an onboarding.

## Related

- `docs/architecture/permission-aware-retrieval.md`, sections "Three deployment shapes, one mechanism" and "Resolving group membership"
- OpenSpec change `add-auth-and-identity`, decisions D1, D2, D2a, D4, D9, D15 and D19, capabilities `identity-provider` and `identity-brokering`
- ADR-014, which decides which membership path is primary once directory lookups exist, and which is deferred with them
- ADR-015, which decides how group identifiers cross the broker, and which is deferred because none do in this version
- ADR-010 and ADR-012, deferred for the same reason
- OpenSpec changes `add-tenant-isolation`, `add-usage-metering-and-quotas`, and `add-audit-and-gdpr-compliance`, whose single-issuer assumption this record confirms rather than disturbs
