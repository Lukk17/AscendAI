# ADR-010: Directory Lookups Are Configured Separately From the Token Issuer

## Status

Proposed, 2026-09-04. Accepted when the OpenSpec change `add-auth-and-identity` lands. This file is the draft that task 14.3 installs into `AscendAgent/docs/architecture/decisions/`, taking the next free number at that time.

## Context

`add-auth-and-identity` promised that any OIDC-compliant identity provider works by repointing `spring.security.oauth2.resourceserver.jwt.issuer-uri`, with a tolerant role-claim converter as the only provider-specific code in the agent. That promise was accurate while identity meant authentication: validate a signature, read a subject, map roles.

Permission-aware retrieval breaks it. `docs/architecture/permission-aware-retrieval.md` requires the caller's transitive group membership on every request, and ADR-M007 fixes how it is obtained: the token's group claim when it is complete, otherwise the provider's transitive membership endpoint. A transitive membership endpoint is vendor-specific by construction. Microsoft Graph and the Google Workspace Directory API do not share a URL shape, an authentication model, a pagination scheme, or a response body.

The design document also names a customer shape where the two are not even the same vendor. Shape 3 signs in through Microsoft Entra ID and stores files in Google Drive, so the groups that decide what can be retrieved live in a directory that never issued the token being validated. A configuration model with one provider slot cannot express that customer at all.

The monorepo records cover the surrounding decisions. ADR-M007 fixes the resolution order, ADR-M008 fixes the cross-provider join, and ADR-M009 fixes where enforcement lives. None of them says how the two providers are configured, and a single `issuer-uri` property silently assumes they are one.

## Decision

The token issuer and the directory are two independent configuration axes.

- `spring.security.oauth2.resourceserver.jwt.issuer-uri` stays exactly what it is and keeps its current meaning: the single issuer whose tokens are validated.
- `app.identity.claims` maps that issuer's claim names onto the resolved identity's fields: which claim is the directory subject, which is the group claim, which is the email. Entra ID is `oid`, `groups`, `email`. Google is `sub`, no group claim, `email`. Keycloak is `sub`, `groups`, `email`.
- `app.identity.directories` is a list of directory adapters. Each entry names a provider kind (`microsoft-graph` or `google-directory`), the principal namespace its groups mint into, and its own credentials. An empty list is valid and means the token's group claim is the only source of groups.

Two adapters ship: Microsoft Graph and Google Directory, behind one interface with one method, transitive group membership for a directory subject. A third vendor is new code, and the documentation says so rather than implying a property change would cover it.

## Consequences

### Why this way

- The split-provider customer is a configuration rather than a fork. The Entra token supplies `entra:group:*` principals, the identity link from ADR-M008 supplies the Google account id, the Google Directory adapter supplies `google:group:*` principals for that account, and both land in one principal set through the same code path as every other shape.
- The customer with no corporate directory is expressible without a special case. The adapter list is empty, the token claim is the only group source, and if there is no group claim either then every principal set is the tenant floor, which is correct and merely coarse.
- The portability claim becomes checkable. Anybody reading the configuration can see which half of it is properties and which half is an adapter, instead of discovering during a customer onboarding that the promised property change needs a class.

### Trade-offs

- More configuration surface than one property, and a misconfigured claim-name mapping is a new way to get an empty group set. Mitigated by the startup check that a deployment with directory adapters configured also has a directory-subject claim mapped, and by the principal-set-size metric the design document already requires.
- Credentials for a directory are a second secret per deployment, with their own rotation story, and a directory client secret that expires produces the failure ADR-011 turns into a 503.
- Two adapters is not a plugin system, and it is not meant to be. A vendor beyond Microsoft and Google is a code change, deliberately, because a generic directory abstraction built before a second real customer needs it would be built against guesses.

### Alternatives considered

- One provider slot, directory inferred from the issuer. Simplest, and it covers Shapes 1 and 2 exactly. Rejected because it cannot express Shape 3 at all, and Shape 3 is the case the design document says the whole cross-provider join exists to serve.
- A generic directory abstraction driven entirely by configuration: endpoint URL, response path, pagination style. Rejected as YAGNI dressed as flexibility. It would encode Graph's and Google's current response shapes into properties, break on either vendor's next revision, and still not handle their different authentication models.
- Resolve groups only from token claims and refuse issuers that cannot emit them. Rejected because Entra ID stops emitting `groups` for exactly the heavily-permissioned users who need it most, which ADR-M007 already records as the `_claim_names` trap.

## Related

- `docs/architecture/permission-aware-retrieval.md`, sections "Resolving group membership" and "Three deployment shapes, one mechanism"
- `docs/architecture/decisions/ADR-M007-group-principals-membership-at-login.md`
- `docs/architecture/decisions/ADR-M008-email-join-with-provider-identifiers.md`
- OpenSpec change `add-auth-and-identity`, decisions D9 and D13, capability `identity-provider`
