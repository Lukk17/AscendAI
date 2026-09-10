# ADR-012: Identity Links Live in PostgreSQL With a Three-State Lifecycle

## Status

Deferred, 2026-09-04. Not implemented by the OpenSpec change `add-auth-and-identity`, and not accepted by it. This file is the draft that task 12.8 installs into `apps/ascend-agent/docs/architecture/decisions/` with this status intact, taking the next free number at that time.

## Deferral, 2026-09-04

The link joins a person's login identity to their file-store identity across two providers. In this version there is one provider, Keycloak, and one subject, and group principals come from Keycloak realm groups rather than from either directory. There is nothing to join, so the `identity_link` table, the three-state lifecycle, and the administrator API that corrects a link are all out of scope. No Liquibase changelog and no `/api/v1/admin/identity-links` surface ship.

Nothing below was found to be wrong, and three parts of it are worth more than the table they describe. The three-state lifecycle, where a detected discrepancy and an administrator's deliberate switch-off need different names because they need different responses. The email normalization function, and specifically the refusal to strip dots, because dot-insensitivity is one provider's local-part behaviour rather than an email rule and applying it generally merges two genuinely different corporate addresses into one person. And the deletion of the cached principal set on a successful correction, without which an administrator fixes a link, the affected person still finds nothing for minutes, and the obvious conclusion is that the fix did not take.

What has to happen for this record to become active: directory-sourced group principals have to exist, so that a person's identity at the directory whose groups an access list names has to be connected to their Keycloak identity at all.

One consequence to carry forward: `add-audit-and-gdpr-compliance` was written expecting to inherit `identity_link` into its erasure scope. That table does not exist in this version, and that sibling's erasure scope shrinks accordingly.

## Context

ADR-M008 decides that a person's login identity and their file-store identity are joined on the normalized email address, that each provider's own stable identifier is stored alongside it, and that a conflict between the two is marked rather than resolved automatically. It also says an administrator API to inspect and correct mappings is part of the decision rather than an operational extra.

What it does not decide is anything about the record itself: where it lives, what states it can be in, what those states are called, or what the administrator API looks like. Those are implementation decisions with real consequences, and leaving them to the first person who writes the class means the state machine gets discovered rather than designed.

Three of them matter enough to record. The store has to survive a cache flush and be queryable from two directions, by email and by either provider subject. The lifecycle has to distinguish a discrepancy the system detected from an administrator's deliberate decision to turn a link off, because those two produce the same restriction for different reasons and an administrator needs to tell them apart. And the email normalization function has to be one function, because ADR-M008's own risk section says the join fails when two call sites normalize differently.

## Decision

The link is a PostgreSQL table, `identity_link`, created by a Liquibase changelog like every other schema change in this module. It holds the normalized email, the login issuer, the login provider's directory subject, the file provider's directory subject where known, the status, the creation and last-confirmation timestamps, and the conflicting subject recorded at detection time. It is unique on normalized email within a tenant and indexed on each subject.

The lifecycle has exactly three states:

| Status | Set when | Group principals contributed |
| :--- | :--- | :--- |
| `ACTIVE` | Created at first login, or confirmed when every stored provider subject matches the one presented | All groups from both providers |
| `SUSPECT` | The same normalized email presented a provider subject that differs from the one on file | None |
| `DISABLED` | An administrator turned the link off | None |

ADR-M008 calls the conflict state broken. `SUSPECT` is the same state under a name that describes what is actually known: a discrepancy was detected, and which side is wrong has not been established. Nothing about the record claims the person is an impostor, and the name should not either.

Email normalization is one function applied identically at login and at any later reconciliation: trim, Unicode NFKC, lowercase, IDNA-encode the domain, strip a `+tag` suffix from the local part. It does not strip dots.

The administrator API is three endpoints, all requiring `ADMIN`: a cursor-paginated list filterable by status and email, a single-link read that includes the conflicting subject, and a `PATCH` that corrects a provider subject or moves the status. A successful correction deletes that person's cached principal set so the fix takes effect on their next request rather than after the cache time to live.

## Consequences

### Why this way

- PostgreSQL rather than Redis because a link is durable state an administrator corrects and an auditor asks about, not a cache. It has to outlive a Redis flush, and it has to be queried by email and by either subject, which is a table with two indexes rather than a key-value lookup.
- Three states rather than two because "the system detected a discrepancy" and "a human decided to switch this off" need different responses. The first is a queue of things to investigate. The second is a deliberate configuration that must not reappear in that queue every time somebody triages it.
- Not stripping dots is the part most likely to be undone by somebody being helpful. Dot-insensitivity is one provider's local-part behaviour, not an email rule, and applying it generally merges two genuinely different corporate addresses into one person. That is the same silent-inheritance failure ADR-M008 exists to prevent, reached from the opposite direction, which is why it is written down here rather than left to the normalizer's author.
- Deleting the cached principal set on correction is what makes the administrator API feel like it works. Without it the administrator fixes a link, the affected person still finds nothing for up to five minutes, and the obvious conclusion is that the fix did not take.

### Trade-offs

- The table stores email addresses, which are personal data. That is why the administrator API is `ADMIN` only, why the stored value is normalized rather than raw, and why `add-audit-and-gdpr-compliance` has to take this table into its erasure scope. It is a new place personal data lives and it should be counted as one.
- An administrator can set a wrong subject through the `PATCH` endpoint, and doing so grants that person the other identity's group principals. This is a real privilege, held by a real role, and it is the same privilege an administrator already has in the directory itself. It is not mitigated further, and it is a reason the endpoint is `ADMIN` and not something looser.
- A link left in `SUSPECT` is a person operating on the tenant floor indefinitely, and nothing in this decision escalates it. The list endpoint filtered by status is how it gets found, which requires somebody to look. An alert on suspect-link count is worth having and is not specified here.
- The table adds a per-login read on the request path. It is a single indexed lookup by normalized email, well inside the budget the directory call already occupies, and it is not cached, because a stale link status is the one thing that would let a `SUSPECT` person keep their principals.

### Alternatives considered

- Keep the link in Redis alongside the principal cache. Pro: one store for identity-derived state, no schema change, no migration. Con: it is not a cache, and a flush would discard the reconciliation history and every administrator correction, silently recreating links as `ACTIVE` at the next login. That converts a detected conflict back into a silent inheritance, which is the failure this record inherits from ADR-M008. Rejected.
- Two states, active and broken. Pro: simpler, and it matches ADR-M008's wording exactly. Con: an administrator who deliberately disables a link has no way to say so, and the only available state also means "something is wrong here, investigate", so deliberate decisions pollute the investigation queue permanently. Rejected.
- Auto-heal a conflict by trusting the most recent login. Pro: no support ticket, no administrator involvement, and the common case (somebody's identifier genuinely changed) resolves itself. Con: it is precisely address reuse, accepted automatically, which is the bug ADR-M008 rejects in its Alternative 3. Rejected.
- Normalize by stripping dots as well as tags. Pro: joins Gmail-style addresses that differ only by dots, which a consumer-facing product would want. Con: merges distinct corporate addresses into one person and grants one of them the other's access. Rejected, and named explicitly above so it is not reintroduced as a bug fix.

## Related

- `docs/architecture/permission-aware-retrieval.md`, section "The cross-provider identity join"
- `docs/architecture/decisions/ADR-M008-email-join-with-provider-identifiers.md`
- OpenSpec change `add-auth-and-identity`, decisions D11 and D12, capability `identity-linking`
- OpenSpec change `add-audit-and-gdpr-compliance`, which inherits `identity_link` into its erasure scope
