Ordering rule for this change: the tenant claim and the principal contract exist before anything reads them, and nothing here edits a class of `add-keycloak-login`. Sections 1 to 5 add the realm content, the tenant claim, the principal format and the principal set through the extension points of `add-keycloak-login` D22. Section 6 adds optional corporate sign-on, and nothing before it depends on it.

Build order: build group 5, position 1 of the owner build order of 2026-10-04 (which supersedes the company order of 2026-10-01), after every web-hunter, base and personal change. This change needs `add-keycloak-login` applied: the realm, the resource server, the resolved identity with `TenantResolver` and `IdentityContributor`, the `ascend-agent-directory` client, the development overlay and the e2e token helper of its task 10.2.

Blocked siblings. `add-tenant-isolation` cannot compose an access-list predicate until a principal set exists on the request, and `add-document-connectors` cannot write access lists until the principal format is fixed. The tasks they wait on are section 2 (the tenant claim), section 3 (the principal format, its factory and the contributor), and task 4.1 (the assembled set on the request). Those are the contract freeze. Neither sibling starts before all of them are done and their verifications pass.

Every task carries its own verification, and every verification is an observable check: a status code, a response body, a stored row, a call that was or was not made, a value on a resolved object. None of them is a log line.

## 1. Realm additions to the export and the overlay of add-keycloak-login

- [ ] 1.1 Add to the production realm export `keycloak/realm-ascend-ai.json` a protocol mapper emitting the `tenant` user attribute as the `tenant` claim on the `ascend-flutter` client
  - verify: `jq` shows the mapper, a token of a realm user with the attribute `tenant` of `acme` carries `tenant: acme`, and a token of a user without the attribute carries no `tenant` claim
- [ ] 1.2 Add realm groups and the group protocol mapper to the export, with at least one seeded group demonstrating the principal character set
  - verify: `jq` shows the group membership mapper on the `ascend-flutter` client emitting a full-path-free array claim, and a token for an account in the seeded group carries that group name in the claim
- [ ] 1.3 Add the realm group `dev-all` to the development overlay of `add-keycloak-login`, with the seeded development user in it
  - verify: a token of the seeded development user carries `dev-all` in its group claim, and a production-only import has no `dev-all` group
- [ ] 1.4 Verify the company claims contract on a real token
  - verify: a token for the seeded overlay user decodes to the claims of `add-keycloak-login` task 1.10 plus a group claim containing `dev-all`, and no `tenant` claim, so the agent resolves tenant `default`

## 2. Tenant claim (contract freeze, blocks add-tenant-isolation)

- [ ] 2.1 Register the claim-reading `TenantResolver` bean of design D3b: the `tenant` claim of a token and the `tenant` attribute of a Keycloak user representation, each defaulting to `default` when absent. The default bean of `add-keycloak-login` then does not exist
  - verify: a token carrying `tenant: acme` resolves `acme`, a token without it resolves `default`, the dev identity resolves `default`, and a resolution without a token of a user whose attribute is `acme` resolves `acme`
- [ ] 2.2 Tests for the tenant contract, including the `ADMIN` lookup of `add-keycloak-login` task 3.8 with several tenants
  - verify: tenant `acme` with two enabled `ADMIN` users and tenant `globex` with one return exactly the two `acme` administrators for `acme`, and `TenantContext.currentTenantId()` answers `acme` inside a request of an `acme` user

## 3. Principal identifiers, the typed factory and the contributor (contract freeze, blocks add-tenant-isolation and add-document-connectors)

- [ ] 3.1 Create the principal value type and its single factory, validating the `namespace:type:id` shape, the 128-character cap, and the character set of lowercase letters, digits, `.`, `-`, `_`, `@`
  - verify: the factory produces exactly `local:group:policy-readers` and `tenant:everyone:acme` for the corresponding inputs
- [ ] 3.2 Model the closed namespace set (`local`, `tenant`) and the closed type set (`group`, `everyone`) as enums, with every Keycloak realm group minting into `local`
  - verify: a token carrying the realm group `policy-readers` resolves `local:group:policy-readers`, and a request for a namespace outside the set fails to compile or throws
- [ ] 3.3 Reject invalid input by throwing rather than by returning a truncated or best-effort value
  - verify: uppercase input, a space, a namespace outside the set, and a 129-character value each throw an exception naming the violated constraint, and no principal value is produced
- [ ] 3.4 Make the factory the only construction path: the principal type has a private constructor and one public static factory method, so the compiler refuses a construction anywhere else (owner answer 93 of 2026-10-08, review item C7, in place of an ArchUnit rule)
  - verify: a unit test reads the principal type's declared constructors and finds only private ones, and the factory method is the only public member that returns a principal
- [ ] 3.5 Register the `IdentityContributor` of design D3c that adds `PrincipalSet` to the resolved identity's extensions on the token path, the dev path and the path without a token. The raw group names are not stored next to it, because nothing reads them (owner answer 93 of 2026-10-08, review item B9). Bind the group claim name under `app.identity.claims` with the Keycloak default `groups`: the property `app.identity.claims.groups`, a setting under owner rule 98 of 2026-10-08 with the same default in `application.yaml` (`${APP_IDENTITY_CLAIMS_GROUPS:groups}`), in the properties record and in the `ascend-agent` compose line `- APP_IDENTITY_CLAIMS_GROUPS=${APP_IDENTITY_CLAIMS_GROUPS:-groups}`
  - verify: a token carrying two groups resolves both as `local:group:*` principals in `PrincipalSet`, the extensions hold no other value of this change, an integration test overriding the group claim name resolves the groups from the overridden claim without a code change, and an architecture test asserts no class of `add-keycloak-login` imports a class of this change and that a context without this change's beans still starts with tenant `default` and empty extensions
- [ ] 3.6 Add `PrincipalContext.currentPrincipals()` in the package `com.lukk.ascend.ai.agent.security` (owner decision 65.23 of 2026-10-04), returning `Optional<PrincipalSet>` from the extensions of the current request's identity and throwing outside a request with a resolved identity
  - verify: an identity with no contributor value answers an empty `Optional`, a resolved set with no group answers a present empty-group set holding only the tenant pseudo-group, and a call on a thread with no resolved identity throws

## 4. Group membership and principal set assembly

- [ ] 4.1 Resolve the groups from the configured group claim, mint one principal per group through the factory, assemble the set during authentication before any controller method runs, attach it to the resolved identity, and make it immutable for the life of the request (contract freeze, blocks add-tenant-isolation)
  - verify: the set observed in a controller equals the set observed at authentication time, any mutation attempt throws, the set always contains `tenant:everyone:{tenantId}`, and a token listing two groups resolves both as `local:group:*` principals
- [ ] 4.2 Resolve an absent or empty group claim to no group principals, and make no outbound call of any kind during resolution from a token
  - verify: a token with no group claim resolves exactly `tenant:everyone:{tenantId}` and the request returns 200, and a network stub asserts that resolution issues no HTTP call
- [ ] 4.3 Prove that nothing is cached between requests on the token path, so a group change reaches the agent with the next token (owner answer 93 of 2026-10-08, review item C6: that Keycloak issues the next token without a removed group is Keycloak's behaviour and is not tested here, and no principal set cache is built that a Redis check could look for)
  - verify: two requests for the same subject, the first with a token whose group claim lists `finance` and the second with a token whose group claim does not, resolve `local:group:finance` for the first and not for the second
- [ ] 4.4 Fail loudly on a group name that cannot be minted
  - verify: a token carrying a group name with a character outside the permitted set answers 403 `application/problem+json` with a `detail` naming the constraint, the same refusal as the principal cap of task 4.5, and no partially-populated set reaches any filter
- [ ] 4.5 Enforce the configurable cap, default 256, refusing rather than truncating. The cap is the property `app.identity.max-principals`, a setting under owner rule 98 of 2026-10-08 with the same default in `application.yaml` (`${APP_IDENTITY_MAXPRINCIPALS:256}`), in the properties record and in the `ascend-agent` compose line `- APP_IDENTITY_MAXPRINCIPALS=${APP_IDENTITY_MAXPRINCIPALS:-256}`
  - verify: a caller resolving more principals than the cap receives 403 with an `application/problem+json` body naming both the cap and the resolved size, and no vector search is executed, and a binding test reads 256 with `APP_IDENTITY_MAXPRINCIPALS` unset and its value when it is set
- [ ] 4.6 Give the dev identity of `add-keycloak-login` the principal set `tenant:everyone:default` and `local:group:dev-all` through the contributor (design D5b), with no edit of the dev chain
  - verify: under `dev`, a chunk stored with `local:group:dev-all` in its access list is retrieved by a tokenless prompt request, and a chunk stored with no access list is not
- [ ] 4.7 Publish the principal-set-size metric the design document requires
  - verify: after a request, the metric is present on `/actuator/prometheus` and its recorded value equals the resolved set size for that request
- [ ] 4.8 Assert that roles contribute no principals
  - verify: two callers in one tenant with identical group membership, one holding only `USER` and one holding `ADMIN`, resolve equal principal sets
- [ ] 4.9 Assert that a directory group identifier matches nothing
  - verify: a chunk whose access list names a Microsoft Entra ID group by its directory object id is retrieved by no caller, and a chunk carrying `tenant:everyone:{tenantId}` is retrieved by every caller in that tenant

## 5. Groups and tenant on the path without a token

- [ ] 5.1 In the contributor of task 3.5, read the groups of a user resolved without a token through Keycloak's admin API with the `ascend-agent-directory` client of `add-keycloak-login`, through the same factory and cap as a token
  - verify: an integration test against Testcontainers Keycloak shows equal principal sets and equal tenants for a token and a resolution without a token of the same user, and a user over the cap is refused rather than narrowed
- [ ] 5.2 Confirm the cache of `add-keycloak-login` design D20 holds the extensions too, so the groups are never staler than the realm access token lifetime
  - verify: a group removal is visible on the path without a token once the cache entry is older than the access token lifetime, and not before

## 6. Optional corporate sign-on through identity brokering

Nothing in sections 1 to 5 depends on this section. A deployment that skips it is complete.

- [ ] 6.1 Add a disabled brokered-provider template entry to the realm export: a generic OpenID Connect provider carrying a hardcoded-attribute mapper for `tenant` and token storage off, with no mapper importing a group claim, a role claim, or any other attribute the resolved identity derives authorization from
  - verify: `jq` shows the entry disabled, shows its tenant mapper, shows no identity-provider mapper writing an attribute that any protocol mapper emits into a claim the agent reads for authorization, and shows no provider in the export with token storage enabled
- [ ] 6.2 Stand up a second Keycloak realm as a stand-in for a customer's identity provider, and broker it from `ascend-ai` using the template entry, with its own tenant value
  - verify: a person signing in through the brokered provider reaches a token whose `tenant` claim carries the brokered provider's value and not `default`
- [ ] 6.3 Prove a brokered person's authorization comes from Keycloak and not from the upstream token
  - verify: an administrator places the brokered person in the realm group `policy-readers` and their resolved principal set contains `local:group:policy-readers`, an upstream token carrying its own `tenant` claim naming a different customer yields an access token stamped with the brokered provider's tenant, and an upstream group named `ADMIN` yields no `ROLE_ADMIN` authority and a 403 on an `ADMIN`-only endpoint
- [ ] 6.4 Prove an unmatched person is not dropped into a brokered provider
  - verify: a person whose email domain is registered to no brokered provider is not signed in through one, and signing in with a local account and password still works
- [ ] 6.5 Express the domain to provider mapping with Keycloak Organizations (owner decision 65.15 of 2026-10-04): one organization per customer with its email domain and the linked brokered provider, identity-first login with redirect by domain, set in the realm export's template shape
  - verify: against the pinned Keycloak version, a person who types an email of the organization's domain is redirected to the linked provider, the case of Keycloak issue 40510 (a person of that domain with a local OTP credential and a linked provider) is still redirected, the case of Keycloak issue 37824 (a person who types only a user name whose profile email has the domain) is still redirected, and a person of an unknown domain is not redirected and reaches the password page (task 6.4)
- [ ] 6.6 Document SAML brokering as configuration only in the runbook in `docs/SECURITY.md` (owner decision 65.16 of 2026-10-04): a SAML provider added from the same shape as the template entry, with the tenant stamp mapper and no mapper importing an upstream authorization claim, and no SAML-specific code
  - verify: the runbook names the SAML steps and the review of the change finds no SAML-specific class

## 7. Documentation and architecture decision records

- [ ] 7.1 Add the company sections to `docs/SECURITY.md` of `add-keycloak-login`: the `tenant` claim and its default, the two beans this change registers on the extension points, the principal identifier format, and the dev principal set of design D5b
  - verify: the document names every configuration key this change introduces
- [ ] 7.2 Add the group administration runbook to `docs/SECURITY.md`: creating a realm group, the group-name character constraint the principal factory enforces, assigning membership, and how a group becomes a principal on the next token
  - verify: an operator following the runbook creates a group, assigns a person, and observes the corresponding `local:group:*` principal on that person's next resolved identity, without reading any other document
- [ ] 7.3 Add the optional brokering runbook to `docs/SECURITY.md`: what the customer hands over, creating the brokered provider from the template, the tenant stamp, the organization with its email domain, the verification sign-in that closes the onboarding, and the statement that group membership is assigned separately in Keycloak and no group data crosses the broker
  - verify: an operator following the runbook against the second Keycloak realm from task 6.2 onboards it end to end and reaches a verification sign-in resolving the expected tenant, without reading any other document
- [ ] 7.4 Record the named limitation in `docs/SECURITY.md`: no principal this version mints matches a directory group identifier, so per-document permissions apply to directly-uploaded documents and connector-synced documents are visible tenant-wide, together with what would have to be built to lift it and the mapping owner decision 65.14 of 2026-10-04 names
  - verify: the section states both halves of the consequence and names the deferred work, and it does not describe the limitation as a defect
- [ ] 7.5 Extend the staleness disclosure of `docs/SECURITY.md` to group membership: a group change becomes visible at the caller's next token, bounded by the access token lifetime and the SSO session lifetime, and ascend-ai-agent adds no cache of its own on the token path
  - verify: the stated numbers match the lifetimes set in the realm export of `add-keycloak-login` task 1.3
- [ ] 7.6 Install the two accepted decision records drafted in `openspec/changes/add-auth-and-identity/decisions/` (`ADR-NNN-keycloak-one-realm-one-issuer-customers-brokered` and `ADR-NNN-principal-set-never-silently-narrowed`) into `apps/ascend-agent/docs/architecture/decisions/`, taking the next free numbers at that moment and flipping each Status line from proposed to accepted with the merge date. The four deferred drafts are not installed: they stay in this change's `decisions/` folder, which the archive keeps under `openspec/changes/archive/`, next to the Deferred section of the design (owner answer 93 of 2026-10-08, review item C1)
  - verify: the two files exist under `apps/ascend-agent/docs/architecture/decisions/` with unique sequential numbers, no number collides with an existing record, every relative link inside them resolves, each mention of a deferred record names it as a draft kept in the archived change folder, and no deferred record is under `apps/ascend-agent/docs/architecture/decisions/`
- [ ] 7.7 Update `apps/ascend-agent/docs/architecture/` diagrams and arc42 sections for the principal resolution path on the extension points
  - verify: the component diagram shows the claim-reading `TenantResolver` and the principal contributor plugged into the identity resolver of `add-keycloak-login`, and shows no directory adapter and no principal cache
- [ ] 7.8 Amend `docs/architecture/permission-aware-retrieval.md` and `docs/architecture/decisions/ADR-M007-group-principals-membership-at-login.md` to match what this version actually delivers: group membership resolved from Keycloak realm groups, no directory lookup and no principal cache, the ownership table split into what lands and what is deferred, and the named limitation that a directory group identifier matches no principal
  - verify: neither document still states that this change delivers the directory object id, the principal cache, the identity link, or the identity-link administrator API, the staleness section names the token lifetime as the only window, and every cross-reference between those two documents and this change's decisions resolves
- [ ] 7.9 Keep `openspec/changes/add-auth-and-identity/tasks.md` checkboxes current as work proceeds
  - verify: `openspec instructions apply --change add-auth-and-identity --json` reports a completion count matching the checked boxes at every review point
- [ ] 7.10 Add the rows of this change's two settings to `apps/ascend-agent/docs/CONFIGURATION.md` in the same commit as each setting (owner rule 98 of 2026-10-08): `APP_IDENTITY_CLAIMS_GROUPS` (`app.identity.claims.groups`, default `groups`, the token claim that carries the group names, task 3.5) and `APP_IDENTITY_MAXPRINCIPALS` (`app.identity.max-principals`, default `256`, the principal set cap, task 4.5), each description ending with "Added by `add-auth-and-identity`."
  - verify: each of the two settings has exactly one row, and each row's default equals the compose default and the `application.yaml` default

## 8. End-to-end coverage (owner request of 2026-10-04)

Every company behaviour a caller can see gets an end-to-end test against the live stack, written as `add-keycloak-login` section 10 describes: deterministic Bruno tests first, the shared token helper of its task 10.2 and the authorization probe of its task 10.6, Reset and cleanup scoped to the spec's own users and data, and never a log line as a pass criterion. Each new spec takes the next free number of its suite at implementation time, written `<N>` below.

- [ ] 8.1 Add the test tenants to the development overlay, never to the production export: tenant attribute `e2e-acme` for `e2e-user-acme` (`USER`), `e2e-admin-acme` (`USER`, `ADMIN`), `e2e-finance-acme` (`USER`, realm group `e2e-finance`), tenant attribute `e2e-globex` for `e2e-user-globex` (`USER`) and `e2e-admin-globex` (`USER`, `ADMIN`), and tenant attribute `e2e-soul` for `e2e-user-soul` (`USER`) and `e2e-admin-soul` (`USER`, `ADMIN`), the separate test tenant in which every personality spec of `add-agent-soul` runs once this change lands, because a personality reaches every reply of its tenant (owner answer 67.4 of 2026-10-04). All share the password `${E2E_USER_PASSWORD}` of `add-keycloak-login` task 10.1 (owner answer 67.5 of 2026-10-04). Every company spec and every spec that checks another tenant uses these users (owner answer 67.4)
  - verify: a password grant for each user returns a token whose decoded claims carry the stated `tenant`, roles and groups, and a production-only import yields none of these users
- [ ] 8.4 Move the personality specs of `add-agent-soul` to the test tenant `e2e-soul` in place (owner answers 67.2 and 67.4 of 2026-10-04): until this change lands they run as the e2e users of tenant `default` of `add-keycloak-login`, alone in their lane, and from this change on as `e2e-user-soul` and `e2e-admin-soul`. No spec is replaced by a successor
  - verify: every soul spec names a user of `e2e-soul`, and passes against the stack with this change applied
- [ ] 8.5 Add the deterministic spec `<N>-auth-brokered-sign-in-test.md` once section 6 is implemented, with the overlay realm `e2e-customer` as the stand-in customer identity provider (user `e2e-broker-person` with email domain `e2e-customer.test`, an upstream `tenant` claim `e2e-evil` and an upstream group `ADMIN`) and the organization of task 6.5 linked to it. Bruno folder `ascend-agent/testing/auth-brokered-sign-in/` with `broker-identity-first-login`, `broker-upstream-login-submit`, `broker-code-exchange`, `broker-ingestion-run-refused`, `broker-unknown-domain-login` and `broker-no-stored-token`, driven by plain HTTP as in `add-keycloak-login` task 10.5
  - verify: an email of `e2e-customer.test` is redirected to the stand-in provider, the resulting token carries the brokered provider's `tenant` and neither `e2e-evil` nor `default`, carries no `ADMIN` role and gets 403 on `ingestion-run`, an unknown domain reaches the password page, and the Keycloak admin API shows no stored provider token for the brokered user
- [ ] 8.6 Update `apps/ascend-agent/e2e/README.md`: the spec of 8.5 in the capability table, the test tenants of 8.1, the parallel groups (the spec of 8.5 changes Keycloak state and runs alone among the specs that do, the rest run in parallel), no row, Bruno folder or template for the dropped specs of 8.2 and 8.3, and the "Claude Code permission allowlist" with `Bash(docker exec keycloak /opt/keycloak/bin/kcadm.sh *)` and `Bash(docker exec keycloak sh -c *)`
  - verify: every new spec appears in the suite table with its template, and every command a new spec runs matches an allowlist entry
- [ ] 8.7 Update `docs/E2E_RUN_SCENARIOS.md`: the agent spec of 8.5 in the spec lists of Scenarios 1 to 4 and of the ascend-agent service suite, the test tenants in the preconditions, and the spec counts and the summary table recomputed
  - verify: every new spec is listed in each scenario that runs its suite, and the counts in the summary table equal the sum of the per-suite lists

The tenant claims, the group principals, the principal cap and the character refusal are proved by tasks 1.4, 2.1, 4.1, 4.4, 4.5 and 8.1, so their specs are dropped (owner answer 91.3 of 2026-10-08). The live-stack check of the cap needed 257 seeded realm groups and is not kept (review item C5).

Task 8.2 removed by owner decision 91.3 of 2026-10-08.
Task 8.3 removed by owner decision 91.3 of 2026-10-08.
