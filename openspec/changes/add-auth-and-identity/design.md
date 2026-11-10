## Context

`add-keycloak-login` gives the personal assistant real login (owner answer 70.2 of 2026-10-04): one Keycloak realm `ascend-ai` as the only issuer, password sign-in on Keycloak's own login page, the agent as an OAuth2 resource server on Spring Security 7.1.1, the roles `USER` and `ADMIN` with one authorization matrix that every later change extends, the app client `ascend-flutter`, the confidential clients `ascend-openclaw-host` and `ascend-agent-directory`, the service token for our own services, the identity resolved without a token, the production guard, and one tenant `default`. Until 2026-10-04 all of that was part of this change. It was split out to follow the owner rule of 2026-10-04: the personal assistant comes first, nothing personal, web-hunter or base may depend on company work, and company work comes last and only plugs in through extension points with safe defaults.

This change is the company half. It adds what a deployment serving several customers needs: the tenant claim, groups, group principals for retrieval access lists, corporate single sign-on through brokering with Keycloak Organizations and SAML, and the test tenants of the company specs. It edits no class of `add-keycloak-login`. It plugs in through that change's two ports (`add-keycloak-login` D22): `TenantResolver`, whose default answers `default`, and `IdentityContributor`, which adds typed values to the resolved identity. It is build group 5, position 1 of the owner build order of 2026-10-04, after every web-hunter, base and personal change, and it needs only `add-keycloak-login` (build group 3, position 3) among them.

`docs/architecture/permission-aware-retrieval.md` describes how AscendAI decides which chunks a person may read, and its ownership table assigns six elements of that mechanism here. This version delivers two: the principal identifier format with its typed factory, and group membership resolution. The other four belong to the directory work and are deferred with their analysis intact, in the Deferred section below. The supporting monorepo records are `ADR-M004` through `ADR-M009` under `docs/architecture/decisions/`.

Groups are Keycloak realm groups, created by an administrator, assigned by an administrator, and emitted into the token by a protocol mapper. Nothing is read from a customer's Microsoft or Google directory in this version, and nothing carrying authorization meaning is imported across the broker. Identity brokering is optional configuration for a customer who wants corporate single sign-on. It decides where a person authenticates. It does not decide what they may read.

Constraints:

- Sibling changes depend on this one's contract: `add-tenant-isolation` consumes the `tenant` claim and the principal set defined here, and `add-usage-metering-and-quotas`, `add-audit-and-gdpr-compliance`, `add-tenant-administration` and `add-tenant-policy` key on the tenant of the resolved identity. The claim names must be stable before those changes land.
- `add-tenant-isolation` composes the access-list predicate into the same `SearchRequest` filter that carries the tenant predicate, and it can only do that if a principal set already exists on the request. `add-document-connectors` writes access lists that name principals, and those lists mean nothing until the principal format is fixed. Both are blocked on the identity work here, so the principal contract has to be frozen before either of them starts.
- The principal namespaces this version can actually mint are `local` and `tenant`. A directory group identifier matches nothing, which is a real limitation with a real consequence for connector-synced documents, and it has its own section below rather than a footnote.
- No personal change may depend on anything here. Personal code reads the five named fields of the resolved identity and never an extension value (`add-keycloak-login` D22), so a deployment without this change loses no personal behaviour.

## Goals / Non-Goals

Goals:

- A trustworthy tenant on every identity, read from the `tenant` claim that Keycloak stamps, through the replaced `TenantResolver`.
- Group principals on every request: the resolved identity carries the caller's Keycloak groups converted into `namespace:type:id` principals, assembled once into an immutable set that `add-tenant-isolation` composes into the search filter.
- Optional corporate single sign-on: a customer's own identity provider can be brokered inside the realm as a configured entry, routed by email domain through Keycloak Organizations, and adding one is an administrative procedure rather than a code change or a release.
- Company specs against test tenants that never share state with the personal specs.

Non-Goals:

- Everything `add-keycloak-login` holds: the realm itself, password sign-in, the resource server, the roles and the matrix, the service token, the confidential clients, the identity resolved without a token and the production guard.
- Tenant enforcement (row filtering, collection scoping), which is `add-tenant-isolation`. This change defines and propagates the claim.
- Enforcement of the access-list predicate inside the vector search, the `acl` payload keys, and the `tenant:everyone:{tenantId}` stamp on chunks. Those belong to `add-tenant-isolation`.
- Capturing access lists from SharePoint or Google Drive item permissions at sync. That belongs to `add-document-connectors`, and the Named limitation section below says what this version can and cannot match.
- Reading group membership from a customer's directory, importing group identifiers across the broker, the cross-provider identity link, and the administrator API that corrects one. All deferred, with their analysis preserved below.
- Roles beyond `USER` and `ADMIN`. Roles gate endpoints, principals gate documents. Per-document permission is expressed entirely through group principals, and an `ADMIN` token widens the endpoint matrix while widening retrieval by exactly nothing (ADR-M006).

## Decisions

Decision numbers are stable. D1 to D7 and D20 moved to `add-keycloak-login` on 2026-10-04 with their numbers, so a cross-reference to them now lands there. A decision that has been deferred keeps its number and moves to the Deferred section, so a cross-reference from a sibling change or a decision record still lands on the right text.

### D2b - What this change adds to the realm export of add-keycloak-login

The production realm export of `add-keycloak-login` gains, in this change's tasks:

| Element | Why it is added here |
| :--- | :--- |
| A protocol mapper emitting the `tenant` user attribute as the `tenant` claim | The multi-tenant claim D3b reads. A realm user with no `tenant` attribute carries no claim and resolves `default` |
| Realm groups, and the group protocol mapper emitting them into the access token as an array of group names | The only source of group principals in this version (D9) |
| A disabled brokered-provider template entry, carrying the tenant stamp mapper from D15 and nothing that imports an upstream authorization claim, with token storage off | Onboarding a customer who wants corporate sign-on becomes copying a shape that has been reviewed |
| An organization template for Keycloak Organizations, one organization per customer with its email domain and its linked provider | The domain routing of D15 (owner decision 65.15 of 2026-10-04) |

The development overlay gains the `dev-all` realm group with the seeded development user in it, the test tenants of task 8.1, and the stand-in customer realm `e2e-customer` of task 8.5. None of it reaches the production export.

Of the six decision records drafted in `decisions/`, the two accepted ones are installed into `apps/ascend-agent/docs/architecture/decisions/` (task 7.6). The four deferred drafts stay in this change's `decisions/` folder, which the archive keeps, next to the Deferred section below (owner answer 93 of 2026-10-08).

### D3b - The tenant claim replaces the default tenant

A claim-reading `TenantResolver` bean replaces the default bean of `add-keycloak-login` (its D22). For a token it reads the `tenant` claim, and for the Keycloak user representation of a resolution without a token it reads the `tenant` user attribute. Both default to `default` when absent, which is the normal case for a realm user who arrived through no brokered provider. For a person who arrived through a brokered provider it is the value that provider's hardcoded-attribute mapper stamped (D15). The claim name and the default value are a stable contract. Nothing in this change enforces the tenant. `add-tenant-isolation` owns enforcement.

### D3c - Groups and principals travel as identity extensions

An `IdentityContributor` bean (`add-keycloak-login` D22) adds one typed value to the resolved identity's `extensions`: `PrincipalSet`, the immutable set of D10 built by the D8 factory from the Keycloak group names the caller holds. The raw group names are not stored next to it, because nothing reads them (owner answer 93 of 2026-10-08, review item B9). On the token path the group names come from the configured group claim (D9). On the path without a token they come from Keycloak's admin API through the `ascend-agent-directory` client of `add-keycloak-login`, which already holds `view-users` and so may read a user's groups. Both paths pass through the same factory and the same cap, so a user resolves an equal principal set whether they arrive with a token or through a link.

`PrincipalContext.currentPrincipals()` in the package `com.lukk.ascend.ai.agent.security` (owner decision 65.23 of 2026-10-04) returns `Optional<PrincipalSet>`, read from the extensions of the current request's identity. An empty `Optional` means nothing resolved the set, and a present empty set means a resolved set with no group, so the two stay different at the type level (`add-tenant-isolation` decision 2). It fails closed like `TenantContext` of `add-keycloak-login`: a call outside a request with a resolved identity throws.

Which claim carries the group names is configuration under `app.identity.claims`, next to the email claim name of `add-keycloak-login`: the property `app.identity.claims.groups`, environment variable `APP_IDENTITY_CLAIMS_GROUPS`, default `groups` (owner rule 98 of 2026-10-08).

### D5b - The dev identity carries a usable principal set

The dev identity of `add-keycloak-login` D5 runs the contributors like any other identity, so this change gives it a principal set without touching that chain: when the `dev` profile is active, the contributor answers `tenant:everyone:default` and `local:group:dev-all`. It has to be a usable set. Under the deny-by-default rule from ADR-M006 a chunk matches nobody unless one of its principals appears in the caller's set, so a dev profile that synthesises an empty set hands a developer a knowledge base that answers nothing, with no way to tell that apart from a broken search. `docs/SECURITY.md` records that a locally-ingested corpus has to carry at least one of those two principals to be retrievable under the dev profile, which is a consequence of deny-by-default rather than an exception to it.

### D8 - Principal identifiers: one format, one typed factory

Every principal is `namespace:type:id`, at most 128 characters, restricted to lowercase letters, digits, and `.`, `-`, `_`, `@`, so a principal is safe as a Qdrant keyword payload value and as a Redis set member with no escaping layer anywhere.

The namespaces this version mints are `local` and `tenant`. Types come from a closed set: `group`, and `everyone` for the tenant pseudo-group.

A group defined in our own Keycloak realm mints into `local:group:<slug>`, and every group in this version is such a group. The `entra` and `google` namespaces, and the rule that a directory-sourced group keeps its own directory's namespace, are deferred with the directory work below. They are recorded there rather than dropped, because an access list written from SharePoint item permissions names `entra:group:*` and minting a directory group into `local` would be the wrong answer when that work returns.

| Example | What it names |
| :--- | :--- |
| `local:group:policy-readers` | An application-local group, meaning a Keycloak realm group |
| `tenant:everyone:acme` | The pseudo-group every member of tenant `acme` belongs to |

One typed factory is the only way to construct one. It validates length, character set, namespace, and type, and it throws on anything else rather than returning a best-effort value: an unrecognised namespace is a capture bug, and it fails instead of being stored. Filters are assembled through Spring AI's `FilterExpressionBuilder` and never by string concatenation, which is the rule `add-tenant-isolation` already applies to the tenant predicate, here for the same reason.

Why a factory and not a formatting helper: the format constraints only hold if exactly one place can produce a value. A helper anybody may bypass with string concatenation is a convention, and this has to be an invariant, because a malformed principal is not an error at retrieval time. It simply matches nothing, and the symptom is missing documents.

`tenant:everyone:{tenantId}` is minted by this factory. When it is written onto a chunk is `add-tenant-isolation`'s decision, not this one's.

The namespace enum is a closed set the factory rejects outside of. Adding `entra` and `google` to it later is an additive change to one enum and one configuration key, and the Deferred section records what has to come with them.

### D9 - Group membership comes from the Keycloak group claim

An administrator creates realm groups in Keycloak, puts people in them, and a group protocol mapper in the realm export emits the group names into the access token as an array claim. ascend-ai-agent reads that claim under a configured name and mints one `local:group:<name>` principal per entry through the D8 factory.

That is the whole mechanism. There is no directory call, no second source, and no fallback, so there is no resolution order to get wrong and no completeness test to apply. An absent group claim means the caller is in no groups, which under Keycloak-only membership is a true statement about an administrator's decision rather than a suspicious silence. That is exactly the property that made the previous design's absent claim dangerous, and it is the reason removing the directory removes an entire class of failure along with a capability.

The group names an administrator chooses have to satisfy the D8 character set, since the factory throws rather than mangling. The onboarding runbook says so and the realm export's seeded group demonstrates it.

There is no principal cache on the token path in this version. The previous design cached the resolved set in Redis for the shorter of the remaining token lifetime and five minutes, and it did that to avoid paying a directory round trip per request. Reading a claim off an already-validated token costs nothing worth caching, and a cache here would only add a second staleness window on top of the token's own. The one cache is on the path without a token (`add-keycloak-login` D20), where each resolution is a call to Keycloak's admin API, and it holds a user's identity for at most the realm access token lifetime, so it is never staler than a token would be. The cache design is preserved in the Deferred section, because it returns with the directory call it exists for.

### D10 - The principal set is assembled once, immutable, and capped

The set is assembled during authentication, before any controller method runs, and attached to the resolved identity. It does not change for the life of the request.

Two reasons it is immutable rather than merely computed early. A set that can grow mid-request means the filter composed for the search and the check the presigner runs can disagree, and that gap is exactly where a source reference gets a download link its chunk did not earn. And an immutable set is what makes a request explainable afterwards: one set, one filter, one answer to "why did this person see this".

Contents: `tenant:everyone:{tenantId}` for the caller's tenant, and one principal per Keycloak group the caller holds. Roles contribute nothing.

The cap is 256 principals. A caller whose resolved set exceeds it fails the request with 403 and an RFC 7807 `application/problem+json` body naming the cap, and no search runs on a truncated set. This is the same refusal ADR-M007 applies to an over-long access list, for the same reason: truncating an allow list silently denies people access they genuinely have, and that symptom is indistinguishable from a bug in retrieval, embedding, chunking, or the model.

The number is a decision this change makes, because the design document caps the set without naming a value. 256 is far above any plausible realm-group count for one person, and it keeps the `IN` clause handed to Qdrant to a size the filter evaluates without trouble. It is configurable: the property `app.identity.max-principals`, environment variable `APP_IDENTITY_MAXPRINCIPALS`, default 256 (owner rule 98 of 2026-10-08).

Accessors (owner decision 65.23 of 2026-10-04): `PrincipalContext.currentPrincipals()` of D3c returns the set, and `TenantContext.currentTenantId()` of `add-keycloak-login` returns the tenant. Code that runs on another thread receives the values captured on the request thread, never calls the accessors there.

### D14 - A principal set is never silently narrowed

Two paths could produce a set smaller than the truth, and neither may do it quietly.

A caller whose resolved set exceeds the cap fails the request with 403, per D10, rather than searching on a truncated set.

The dev profile synthesises a deliberate, documented set rather than an empty one, per D5b.

The third path this decision used to cover, a directory call that fails and tempts a fallback to the tenant floor, does not exist in this version because there is no directory call. It returns with the directory work, and its reasoning is preserved in the Deferred section, because the reasoning is the expensive part and it will be needed again.

What remains true and worth stating: the symptom of a narrowed set is not an error. It is a 200 response, a fluent answer, and no sources, and the person who reports it says search is broken. That is why the cap refuses rather than trims, and why the dev profile is not allowed to be empty.

### D15 - Identity brokering is optional configuration for corporate sign-on

A customer who wants their people to sign in with their existing corporate account can have their identity provider brokered inside the `ascend-ai` realm. The mechanism is Keycloak's generic OpenID Connect provider pointed at the customer's own discovery document, or the SAML provider where the customer only offers SAML. ascend-ai-agent never speaks to the customer's provider.

This is optional, and everything else in this change works without it. A customer with no brokered provider has accounts, passwords, groups, and an administrator, which is the normal shape of the product. A customer with a brokered provider has the same thing plus a different front door.

There is no Microsoft-specific provider to reach for and none is needed. Keycloak does ship social and vendor-branded provider types, and the temptation during an onboarding is to pick the one with the familiar logo. The generic OpenID Connect entry pointed at the customer's tenant-specific discovery document is the supported mechanism for a corporate directory, it is what the customer's administrator can actually hand over, and it is what the runbook says to use.

One provider per customer. Not one per person, not one shared entry with per-customer overrides. The alias of that provider is the customer's identifier inside the realm, and one thing hangs off it: the `tenant` value. A hardcoded-attribute mapper on the brokered provider stamps the customer's tenant onto every user who arrives through it, and a protocol mapper puts that attribute into the access token as the `tenant` claim D3 defines.

What does not hang off it, and this is the scope cut stated plainly: nothing about authorization. A person who arrives through a brokered provider is a realm user like any other. Their groups are the Keycloak groups an administrator put them in, and their roles are realm roles assigned on our side. No group claim, and no other attribute carrying authorization meaning, is imported from the upstream token. The upstream provider decides who the person is. It does not decide what they may read.

Two things follow directly, and both are requirements rather than observations. An upstream token that carries its own `tenant` claim naming a different customer has no effect, because the value on the issued token is the one the brokered provider stamped. And an upstream group named `ADMIN` grants no platform role, because no role mapper reads a customer's claim.

How a customer is matched to their provider at sign-in, when one exists. Two mechanisms, and both are in scope: the client application passes the provider alias as a login hint on the authorization request, which is the deterministic path a customer-specific entry URL makes possible; otherwise the realm matches the email domain the person types on the login page to the provider registered for that domain. An unmatched person must not be silently dropped into a default provider, because that is how somebody ends up authenticated into the wrong tenant. A person with no matching domain and a local account signs in with their password, which is the default path and not a failure.

Onboarding a customer onto brokering is an administrative procedure with a written runbook in `docs/SECURITY.md`: the customer hands over their discovery document and client credentials, the operator creates the brokered provider from the disabled template entry in the realm export, sets the hardcoded tenant mapper, registers the email domain, and verifies with a real sign-in that a test person reaches a token carrying the expected tenant. Group assignment is a separate administrative step in Keycloak and is not part of the brokering configuration at all.

### D18 - Membership is as fresh as the token, and the realm sets that bound

Group membership travels in the access token, so a change an administrator makes in Keycloak reaches ascend-ai-agent when the caller next obtains a token. The staleness bound is the access token lifetime, and the realm's SSO session lifetime bounds how long a person can keep refreshing without signing in again. Both are set explicitly in the realm export rather than left at whatever the default happens to be, because they are the number a customer is told.

There is exactly one such window in this version, and it is worth saying so, because the previous design had two that were easy to conflate. Nothing in ascend-ai-agent caches a set resolved from a token (D9), so there is no second window on top of the token's own. A set resolved without a token (`add-keycloak-login` D20, with the groups of D3c) is cached for at most the access token lifetime, the same bound. An administrator who needs a removal to take effect immediately ends that person's sessions in Keycloak, which is an administrative action with an immediate effect rather than a configuration change.

`docs/SECURITY.md` records the number as a product disclosure, and the number it records is the one the export actually sets.

### D19 - Brokered providers do not store upstream tokens

No brokered provider is configured to store the token it received from the customer's identity provider, and ascend-ai-agent does not retrieve upstream provider tokens through the broker.

In this version there is nothing to use one for, and storing one would put a third party's live credentials in our database, turning an identity store into a credential store and pulling every one of those tokens into the erasure and breach scope that `add-audit-and-gdpr-compliance` inherits. Stored tokens stay off in the realm export and off in the onboarding template.

The case that would make this a real question, a customer who will not consent to an application identity reading their directory but will consent to their own people reading their own membership, only arises when directory lookups exist. It is recorded in the Deferred section with the rest of that work.

## Named limitation: connector-synced documents are company-visible in this version

This is the one place where the scope cut changes what a customer gets, rather than only what we build, and it is written out here rather than softened into a caveat.

A document synced from a customer's own storage carries that source's group identifiers in its access list. SharePoint names an Entra ID security group by its directory object id. Google Drive names a Workspace group by its address. This version mints principals only from Keycloak realm groups, in the `local` namespace, and a Keycloak group name will never equal an Entra directory object id. So an access list captured from a customer's storage matches nobody, for everybody, always.

The consequence has two halves and both matter:

- Per-document permissions do work for documents uploaded directly into the product, where an administrator assigns Keycloak groups to a document and the caller's principal set contains those same groups. That is a complete, correct, useful mechanism and it is the one the product ships with.
- Per-document permissions match nothing at all for documents synced from a customer's own storage. Under deny-by-default (ADR-M006) that would make every synced document invisible to everybody, which is the worst possible reading of a scope cut: the feature appears to work, the sync reports success, and nobody can retrieve anything.

For this version, therefore, a connector-synced document is visible to everyone in the company. It carries `tenant:everyone:{tenantId}` and nothing else, which is the behaviour `add-document-connectors` described before it was amended to capture source access lists. That is an honest coarse answer rather than a silent denial, and it is stated to a customer as a product fact rather than left for them to discover.

What would have to be built to lift it, which is analysis this change already did and which survives in the Deferred section below rather than being deleted:

- Directory group identifiers have to reach the agent, either by a directory lookup against the customer's provider or by import across the broker. Both routes were designed here, with their failure modes, and both are deferred.
- The principal namespaces `entra` and `google` have to be added to the D8 closed set, so a directory group mints into its own directory's namespace rather than into `local`.
- A person's Keycloak identity has to be connected to their identity at the directory whose groups the access lists name, which is the cross-provider identity link, deferred as D11 and D12.
- And a decision has to be taken that this change deliberately does not take: how a directory's groups relate to Keycloak's, whether they are imported, mirrored, mapped by an administrator, or bypassed entirely by resolving membership at the directory. That is the owner's decision when the time comes, and inventing a mechanism here would be guessing at it.

Until then, the honest statement to a customer is that synced documents are company-wide and directly-uploaded documents can be restricted to groups.

## Deferred

Everything in this section was designed, checked against primary sources, and then taken out of scope by the decision that groups live in Keycloak only. None of it is wrong. It is not needed until directory-sourced groups are, and it is kept here because re-deriving it would cost more than reading it.

### Deferred D3a - The directory subject, and the Entra ID pairwise-subject trap

The resolved identity used to carry two subjects. `sub` partitions storage. A second field, `directorySubject`, was the only value used for directory calls and for comparison against a provider's permission entries, and the two never substituted for one another.

The reason is specific and it is a trap rather than a preference. Microsoft Entra ID issues a pairwise `sub`: unique per user per application, so two applications receive two different values for the same person, and Microsoft Graph has no concept of it at all. Graph expresses group membership and item permissions against `oid`, the immutable directory object id. A resolver that calls Graph with `sub` gets an empty group list back. Every token still validates, every request still returns 200, and every caller ends up holding nothing but the tenant floor. The failure is invisible at the authentication layer and total at the authorization layer.

On a directly-issued token the directory subject is `oid` for Entra and `sub` for Google. On a brokered token it is whatever the realm's protocol mapper emits from the imported attribute. The test that catches this by construction rather than by review is the one where a token carries different values in `sub` and `oid`, and swapping the two claim values swaps the two identity fields.

Also deferred with it: rejecting a token that carries no value under the configured directory-subject claim when at least one directory adapter is configured, rather than substituting `sub`.

### Deferred D9a - Directory lookup as the primary membership path, and the group emission cap

Where a directory adapter is configured, it was to be called on every cache miss and its answer used, with the token group claim read only when no adapter was configured. The directory was the primary path and the claim was the small-tenant fast path, and the ordering was the consequential part.

The reason is a cap. Microsoft limits the groups claim to 200 group identifiers for the token protocols and 150 for SAML, counting nested groups. Above the cap it does not truncate the list. It emits no groups claim at all and substitutes a pointer to a Graph endpoint, which is what the `_claim_names` and `_claim_sources` overage markers describe. That is not rare in a company of any size, and it lands on precisely the people who belong to the most groups.

Brokering makes it worse. The agent reads a Keycloak token, and the only group data in it is whatever an Attribute Importer copied across. That importer copies a JSON array of textual elements. The overage markers are not an array of strings, so they cannot cross the broker, and under force synchronisation mode the attribute is correctly removed when the upstream claim is absent. The result for an over-cap person is an empty group claim carrying no marker of any kind, which is byte-for-byte what a person who genuinely belongs to no groups looks like. On the brokered path the completeness test is not merely unreliable, it is unimplementable, because there is nothing in the token to test.

Where the agent validates a directly-issued token the completeness test still works and still earns its place: a group claim is complete only when it is present and neither `_claim_names` nor `_claim_sources` appears, and an absent claim means fall through to the directory rather than an empty group set.

Nested groups are flattened by the provider's transitive endpoint on both paths. Both vendors publish one precisely so nobody reimplements their nesting semantics, cycle handling, and limits in order to reach the same answer more slowly and more wrongly.

### Deferred D9b - The Redis principal-set cache

The resolved principal set was cached in Redis under `principals:v1:{issuerHash}:{subject}`, with a time to live of the shorter of the remaining token lifetime and five minutes, to avoid a directory round trip per request.

The key shape is load-bearing and worth keeping. The subject alone is not safe: Entra issues a pairwise `sub`, so the same string can belong to different people under different issuers, and a deployment that repoints its issuer would otherwise serve the previous issuer's cached sets. The `v1` segment lets the cached shape change without a flush. The cached value is the resolved principal set rather than the raw group list, so a hit skips the factory as well as the call. Redis being unavailable degrades latency and not correctness, because every request then pays the directory call and arrives at the same answer.

### Deferred D13 - The login issuer and the directory are configured separately

Configuration separated two axes. `spring.security.oauth2.resourceserver.jwt.issuer-uri`, read from `KEYCLOAK_ISSUER_URI` in every service (owner answer 98.3 of 2026-10-08, default `http://keycloak:8080/realms/ascend-ai`), is the single issuer whose tokens are validated. `app.identity.directories` was a list of directory adapters, each with a provider kind (`microsoft-graph`, `google-directory`), the brokered-provider alias it serves, the principal namespace its groups mint into, and its own credentials. An empty list was valid and meant the token claim was the only source of groups.

The customer this exists for is the split-provider one: login through Microsoft Entra ID, files in Google Drive, so the groups that decide retrieval come from a directory that never issued the token being validated. A configuration model with one provider slot cannot express that customer at all.

The two provider paths are not symmetric, and a document that treats them as a pair produces a Google onboarding that waits for a claim that will never arrive:

| | Microsoft Entra ID | Google Workspace |
| :--- | :--- | :--- |
| Group identifiers in the sign-in token | Emitted only when the customer's administrator configures the optional claim on the application registration, and then only below the emission cap | Never, at any tenant size, under any configuration |
| Group identifiers across the broker | Attribute Importer copies the array when it is present | Nothing to import |
| Primary membership path | Microsoft Graph transitive `memberOf` against the directory subject | Google Workspace Directory API group listing. There is no other path |
| Claim fast path available | Yes, for a small tenant that has configured the optional claim | No |
| Directory credentials | An application registration in the customer's tenant, consented by their administrator, able to read transitive group membership | A service identity authorized by the customer's Workspace administrator to read the Directory API for their domain |

What is configuration and what is code, so a portability claim stays honest: validating a token, mapping claims onto identity fields, and mapping role claims onto authorities are configuration. Brokering a customer's provider is configuration. Calling a directory is an adapter, one class per provider behind one interface, and a third vendor is new code.

### Deferred D11 and D12 - The cross-provider identity link and its administrator API

A customer who signs in through one vendor and stores files at another has each person represented twice, by two identifiers that share nothing. The only value both systems hold is the email address, so that is the join key, and ADR-M008 is blunt that it is a weak one. The defence is to store each provider's own stable identifier alongside the address rather than instead of it, so a reissued address presents as a conflict instead of as a silent inheritance.

The store was a PostgreSQL table `identity_link` created by a Flyway versioned SQL migration, holding the normalized email, the login issuer, each provider's directory subject, the status, created and last-confirmed timestamps, and the conflicting subject recorded at detection. Unique on normalized email within a tenant, indexed on each subject. PostgreSQL rather than Redis because a link is durable state an administrator corrects and an auditor asks about, and it has to survive a flush.

Email normalization was one function applied identically everywhere: trim, Unicode NFKC, lowercase, IDNA-encode the domain, strip a `+tag` suffix from the local part. It does not strip dots. Dot-insensitivity is one provider's local-part behaviour rather than an email rule, and applying it generally would merge two genuinely different corporate addresses into one person, which is the same silent-inheritance failure arrived at from the other direction.

Three states: `ACTIVE` contributes all groups from both providers, `SUSPECT` is a detected discrepancy whose correct side has not been established and contributes none, `DISABLED` is an administrator's deliberate switch-off and contributes none. A `SUSPECT` or `DISABLED` person keeps the tenant floor, can still sign in and chat, and never inherits somebody else's access.

The administrator API was three `ADMIN`-only endpoints under `/api/v1/admin/identity-links`: a cursor-paginated list filterable by status and email, a single-link read including the conflicting subject, and a `PATCH` correcting a subject or moving the status. A successful correction deletes that person's cached principal set, so the fix takes effect on their next request rather than after the cache expires. Without that deletion the administrator fixes a link, the person still finds nothing for minutes, and the obvious conclusion is that the fix did not take.

This is deferred rather than removed because it has no consumer in a Keycloak-only world. There is one provider, one subject, and nothing to join.

### Deferred D14a - A failed directory resolution fails the request

A directory call that fails, whether by Graph throttling, an expired client secret, or an outage, was to fail the request with 503 and a `Retry-After`. It does not fall back to the tenant floor, and it does not serve a cached set past its time to live. Both of those produce a caller who is authenticated, receives 200, and cannot find documents they can open in SharePoint, which is the most expensive symptom in the whole design because it is indistinguishable from a retrieval bug.

The trade-off was stated rather than hidden: this makes directory availability into product availability on the cache-miss path. A 503 is a page for the operator. A narrowed set is somebody's week spent debugging embeddings.

### Deferred D16 - Carrying group identifiers across the broker, force mode, and the user profile declaration

Where a customer's group identifiers were to be taken from their sign-in token, the route was single and documented: an Attribute Importer mapper on the brokered provider copies the array claim element by element into a multivalued user attribute, and a protocol mapper puts that attribute into the access token as an array. Attributes written this way are administrator-context by default, so the signed-in person cannot write their own group list, which is the property that makes trusting the resulting claim defensible at all.

Three configuration points, each with a wrong setting that produces an authorization bug rather than an error:

- The synchronisation mode must be force. Under force the attribute is refreshed on every login and actively removed when the claim is absent, so a person removed from every group genuinely loses those principals at their next login. Under import it is written once at first login and never updated, freezing permissions at the moment somebody first signed in. The default is not force. A mapper created by clicking through the console and accepting defaults produces the frozen-permissions build, and nothing about it looks wrong.
- Every imported attribute must be declared in the realm's declarative user profile, administrator-writable and not user-writable. Since Keycloak 24 the user profile is enabled by default and an undeclared imported attribute is dropped silently. That default flipped in a minor release and turned working configurations into silently failing ones.
- The imported claim must be an array of textual elements. An array of objects is dropped with a warning, and a customer whose provider emits group objects needs the claim reshaped on their side. This is also why the Entra overage markers cannot cross the broker.

All three failures are silent, so configuration review is not the control. The control is a test that no code review substitutes for: remove a person from a group at the customer's directory, have them sign in again, and assert that the principal disappears from their resolved set and that chunks granted by that group only are no longer retrieved for them. It is the only test that tells force mode from import mode from outside.

### Deferred D17 - The customer's administrator has work to do

Microsoft does not emit a groups claim by default, and there is no configuration on our side that changes that. Every enterprise onboarding therefore had a step belonging to the customer, whichever product had been chosen, and a runbook that does not name it produces an onboarding that stalls with each side waiting for the other.

The customer's side, before anything is created in our realm: an application registration in their tenant carrying the broker's redirect URI, with its client credentials handed over; the optional groups claim configured on that registration with the group kinds chosen, if and only if the claim fast path is wanted; consent for the directory adapter to read transitive group membership in their tenant; and for a Google Workspace customer, a service identity authorized to read the Directory API for their domain, because for them there is no claim path at all. The exact Graph application permission constant was to be filled in during implementation against current vendor documentation rather than asserted from memory.

Under the current scope the customer-side prerequisite for brokering is only the application registration and its credentials. Everything about groups is our administrator's job in Keycloak.

### Deferred D18a - Membership is only as fresh as the last brokered login

Nothing refreshed group attributes between logins. A brokered provider writes its attributes at login and at no other time, so a group change at the customer's directory reached Keycloak when the person next signed in through the broker and not before. On the claim membership path the real staleness bound was therefore the realm's SSO session lifetime plus the access token lifetime, set by realm configuration rather than by anything in ascend-ai-agent.

That is a second window alongside the principal cache, and the two bound different things. The cache bounds how long ascend-ai-agent keeps its own copy of a resolved set. The session bounds how long the source of that set stays stale. Expiring the cache faster does not help on the claim path, because a fresh resolution reads the same stale attribute out of the same unchanged token. This was one of the arguments for the directory being the primary path: it is the only one of the two whose revocation window is bounded by something we set.

### Deferred D19a - Stored provider tokens as an escape hatch

Keycloak can store the token it received from the brokered provider and expose it to the application, which would let ascend-ai-agent call the customer's directory as the signed-in person rather than as a configured application identity. It costs an extra call per request and puts a third party's live credentials in our database.

It answers one real problem: the customer who will not consent to an application identity with directory read permission but will consent to their own people reading their own membership. If that customer arrives once directory lookups exist, this is the mechanism, switched on per brokered provider as a deliberate decision with a named cost.

## Test strategy

- Tenant claim: a token carrying `tenant: acme` resolves `acme`, a token without it resolves `default`, and a resolution without a token of a user whose attribute is `acme` resolves `acme`.
- Membership: a token carrying two realm groups resolves two `local:group:*` principals plus the tenant pseudo-group, a token carrying no group claim resolves the tenant pseudo-group alone, and two requests whose tokens carry different group claims for the same subject resolve different sets, so nothing is cached between requests.
- Principal set: assembled once and immutable, so an attempt to add to it after resolution fails, and a resolved set over the cap returns 403 with the cap named and no search executed.
- Roles contribute nothing: two callers with identical group membership, one `USER` and one `ADMIN`, resolve equal principal sets.
- Without a token, against a Testcontainers Keycloak: a token and a resolution without a token for the same user resolve equal principal sets and equal tenants.
- Plug-in only: an architecture test asserts that no class of `add-keycloak-login` imports a class of this change, and that a context without this change's beans still starts with tenant `default` and empty extensions.
- Brokering, which is optional and therefore tested as a separate section rather than as a precondition of anything above: a second Keycloak realm stands in for a customer's identity provider, a person signing in through the broker reaches a token stamped with the brokered provider's tenant, an upstream token claiming a different tenant does not override it, an upstream group named `ADMIN` yields no `ROLE_ADMIN`, and a brokered person's principals are exactly the Keycloak groups an administrator assigned.

## Risks / Trade-offs

- Connector-synced documents are company-visible in this version, so a customer whose SharePoint has genuinely restricted material gets coarser access in AscendAI than they have at the source. This is the Named limitation section above rather than a bullet with a mitigation, it is a product disclosure, and the alternative under deny-by-default was that every synced document became invisible to everybody.
- Group membership is only as fresh as the token that carries it, bounded by the access token lifetime that the realm export of `add-keycloak-login` sets explicitly. An administrator removing somebody from a group takes effect at their next token refresh, not instantly. This is a product disclosure in `docs/SECURITY.md`.
- An administrator creating a group whose name breaks the D8 character set gets a factory that throws rather than a principal that silently matches nothing. That is the right failure, and it is a failure a person can hit while doing an ordinary administrative task, so the runbook names the constraint and the export ships a group that demonstrates it.
- A company bean that throws breaks every request of a company deployment. `add-keycloak-login` D22 fails the request rather than building a half identity, and the contributor tests of task 3.5 cover every path.
- Sibling changes racing on claim names. This change is the declared owner of `tenant` semantics and of the principal format, and `add-tenant-isolation` consumes rather than redefines them.
- The principal-set cap of 256 is a number this change picked rather than one the design fixed. It is far above any plausible realm-group count for one person, it is configurable, and any breach fails loudly with the cap named in the response body.
- Two sibling changes are blocked on this one. The principal format (D8), the tenant claim (D3b) and the principal set (D10) are frozen by the tasks marked as blocking in `tasks.md`, and they land before either sibling starts.
- `add-document-connectors` was written against a principal namespace this version does not mint. That contradiction is resolved by its own scope cut (its D18), and the Named limitation section states what this change can guarantee.
- The test tenants share one Keycloak with the personal e2e users of `add-keycloak-login`. They live in their own tenants and their own groups, and the spec that changes Keycloak state (task 8.5) runs one after the other with the other specs that do.

## Migration Plan

Company work lands after every personal change, so `add-keycloak-login` and its realm are already in place.

1. Add the `tenant` mapper, realm groups, the group mapper, the disabled brokered-provider template and the organization template to the realm export, and the test tenants and the `dev-all` group to the development overlay. Nothing reads any of it yet.
2. Register the claim-reading `TenantResolver` and the principal `IdentityContributor`, and land the principal identifier factory (D8). This is the step `add-tenant-isolation` and `add-document-connectors` are blocked on, and the contract freezes here.
3. Land the principal set with its cap (D9, D10, D14) and the dev principal set (D5b). Retrieval does not read the set yet, so correctness is observable through tests and through the principal-set-size metric before anything depends on it.
4. Land optional brokering, Organizations routing and the SAML runbook. Nothing earlier in this list depends on this step.
5. Land the company end-to-end specs against the test tenants.
6. Rollback: remove this change's two beans. The default beans of `add-keycloak-login` return, every identity is in tenant `default` again with empty extensions, and personal behaviour is unchanged.

## Owner decisions of 2026-10-07

Answer 75.1: the review of 2026-10-07 is fixed here. Item 51: a group name that the principal factory of D8 cannot mint answers 403 `application/problem+json` with a `detail` naming the violated constraint, the same refusal as the principal cap of D10 (tasks 4.4 and 8.3 and the `principal-resolution` spec).

## Open Questions

- Closed (owner decision 65.3 of 2026-10-04): the administrator assignment surface for direct uploads is split. `PUT /api/v1/documents/{id}/access` (first planned in `add-document-management-api` D15, moved to `add-tenant-administration` D8 in the dependency fix of 2026-10-05) and retrieval group create, list and member management through the Keycloak Admin API (its D7), groups named `<tenantId>.<name>` so they mint `local:group:<tenantId>.<name>` through this change's factory. Both are company-only work built after the personal version.
- Closed (owner decision 65.14 of 2026-10-04): directory-sourced groups stay deferred. When they return, a customer's directory groups relate to Keycloak groups through a mapping the administrator writes (a directory group to a Keycloak group of the tenant), not through import, mirroring or resolving at the directory. The Named limitation section stays as written until that work lands.
- Closed (owner decision 65.15 of 2026-10-04): the mapping from an email domain to a customer's brokered provider uses Keycloak Organizations (an organization per customer with its email domain and its linked identity provider, and the identity-first login with redirect by domain). The requirement of D15 stays: a person whose domain matches nothing is not dropped into a default provider. Task 6.5 tests the routing against the pinned Keycloak version, including the two cases of Keycloak issues 40510 (a user with local credentials such as OTP and a linked provider must still be redirected by domain) and 37824 (a user who types only a user name, with the matching domain in the email of the profile, must still be redirected).
- Closed (owner decision 65.16 of 2026-10-04): SAML brokering is configuration only. An operator adds a SAML identity provider in the realm from the same shape as the disabled OpenID Connect template, with the same tenant stamp mapper and no mapper that imports an upstream authorization claim, and the runbook in `docs/SECURITY.md` names the steps. This change writes no SAML-specific code, because no group data crosses the broker in this version.
- Closed (owner decision 65.23 of 2026-10-04): `PrincipalContext.currentPrincipals()` is in this change (D3c), and `TenantContext.currentTenantId()` is in `add-keycloak-login`.
- Closed (owner answer 70.2 and owner rule of 2026-10-04): basic Keycloak login is personal and moved to `add-keycloak-login`. This change keeps only company parts and plugs into that change.

## Owner decisions of 2026-10-08

Answer 93: the small simplifications of the review are applied where no feature is cut. Item C1: only the two accepted decision records are installed, and the four deferred drafts stay in this change's `decisions/` folder, kept by the archive, with their Status lines saying so (task 7.6). Item C7: the principal type has a private constructor and one public static factory method, so the compiler enforces the single construction path in place of an ArchUnit rule (task 3.4). Item B9: the identity carries `PrincipalSet` only, and `GroupMembership`, which nothing read, is gone (D3c, task 3.5, spec `user-identity`). Item C6: task 4.3 no longer tests that Keycloak issues a new token without a removed group, which is Keycloak's behaviour, nor looks for a Redis key of a cache that is never built. It keeps the one check of our code, that two tokens with different group claims resolve different sets. Item C5: the live-stack check of the principal cap with 257 seeded realm groups is dropped with its spec (answer 91.3), and the cap stays proved by task 4.5. The cap itself, the character refusal and the group freshness disclosure of D18 all stay.

Answer 91.3: the deterministic specs of tasks 8.2 (tenant claims) and 8.3 (group principals, the cap and the character refusal) are dropped, because every check they held is proved by a lower test: the token checks of tasks 1.4 and 8.1 and the integration tests of tasks 2.1, 4.1, 4.4 and 4.5. The test users `e2e-groupchange-acme`, `e2e-overcap-acme` and `e2e-badgroup-acme` and the realm groups `e2e-cap-001` to `e2e-cap-257` go with them (task 8.1), and no README row, Bruno folder or template names the dropped specs (tasks 8.6 and 8.7). The brokered sign-in spec of task 8.5 stays, the one live-stack proof of the brokering flow, and the soul specs move to `e2e-soul` as before (task 8.4).

Answer 87 (rule R1): this change holds no cache, lock or queue of its own. The principal set is built from the token on every request, and the path without a token uses the cache of `add-keycloak-login` D20, so no mechanism changed here.

Answer 88 (rule R2): every company plug-in point of this change stays: the claim-reading `TenantResolver`, the `IdentityContributor`, `PrincipalContext` and optional brokering.

Answer 86.1: a Testcontainers integration test of this change that needs an HTTP fake other than Keycloak runs one Mockoon container that loads the shared file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`. The Keycloak integration tests use the Keycloak Testcontainer (answer 89.15 of `add-tenant-administration`).

Answer 85.1: no plan of this change exports a secret in a shell. The e2e user password and the Keycloak admin credentials are read from the repository `.env`, and the Keycloak command line runs inside its container.

Answer 98: every value with a default that this change plans is a setting: the agent reads it from an environment variable, docker compose passes it as `${VAR:-default}` on the `ascend-agent` service, and the code default is the same value. Made external: the group claim name `app.identity.claims.groups` (`APP_IDENTITY_CLAIMS_GROUPS`, `groups`, task 3.5) and the principal set cap `app.identity.max-principals` (`APP_IDENTITY_MAXPRINCIPALS`, `256`, task 4.5), with their rows in `apps/ascend-agent/docs/CONFIGURATION.md` in the same commit (task 7.10). Kept as constants, because they are not operational: the principal format `namespace:type:id`, its 128-character cap and its character set (D8, a format that `add-tenant-isolation` and `add-document-connectors` store and match, so a value per deployment would make stored access lists unreadable elsewhere), the closed namespace and type sets, the claim name `tenant` and its default value `default` (a stable contract, D3b), the dev principal set `tenant:everyone:default` and `local:group:dev-all` (D5b), and the realm, client, group and test user names. The token lifetimes that bound membership freshness (D18) are set in the realm export of `add-keycloak-login`. The deferred directory settings (Deferred D13) are not built. No test of this change uses LM Studio. Stale text fixed by this round (CANON 31.14): the trade-off lines of `decisions/ADR-NNN-directory-is-the-primary-membership-path.md` and `decisions/ADR-NNN-principal-set-never-silently-narrowed.md` no longer point at an open question of this design, which has none on that subject, and name the deferred directory work instead: question 5 under "Open questions" and the section "Deferred: resolving membership from a customer's own directory" of `docs/architecture/permission-aware-retrieval.md`, and Deferred D9a and Deferred D14a of this design.

Answer 98.3: the issuer variable is `KEYCLOAK_ISSUER_URI`, default `http://keycloak:8080/realms/ascend-ai`, the same name in every service. This change adds no issuer setting of its own: it validates tokens of the one issuer of `add-keycloak-login`, and the text of Deferred D13 names the variable next to `spring.security.oauth2.resourceserver.jwt.issuer-uri`.
