# ADR-M008: Join Provider Identities on Email, Keep Both Provider Identifiers

---

### Status

Accepted (2026-09-04)

---

### Context

A customer whose people sign in through Microsoft Entra ID but whose documents live in Google Drive has each person represented twice. The token carries an Entra directory object id. The Drive item permission carries a Google account id and an email address. The two identifiers share nothing, and no directory anywhere maps one to the other.

Without a join, that customer gets a system where every person authenticates correctly and holds no Drive group principals, so the only thing they can retrieve is whatever `tenant:everyone` grants. The product works and knows nothing.

There is exactly one value both systems hold, and it is the email address.

---

### Decision

Join the two provider identities on the normalized email address, and store each provider's own stable identifier alongside it rather than instead of it.

The link record holds the normalized email, the Entra directory object id, and the Google account id. At login, the agent normalizes the email from the token and looks up the link. If none exists, it is created. If one exists and both provider identifiers match, it is confirmed. If one exists and a provider identifier has changed, the link is marked broken: the same address now presents a different subject, which is what address reuse looks like.

A link in the broken state contributes no group identifiers from either provider. The person retains only `tenant:everyone:{tenantId}`. An administrator API to inspect and correct mappings is part of this decision, not an operational extra.

For Microsoft Entra ID specifically, the identifier held on the link is `oid`, the immutable directory object id, and never `sub`. The `sub` claim is pairwise per application, so two applications receive different values for the same person, and Microsoft Graph expresses group membership and item permissions against `oid`. Keying directory lookups on `sub` yields a system that validates every token, returns 200 on every request, and resolves an empty group set for everybody.

---

### Alternatives Considered

#### Alternative 1: Join on email alone, without storing provider identifiers

- Pros: One field, no reconciliation logic, and it works for as long as addresses are never reused.
- Cons: Addresses are reused. Somebody leaves, the address is reissued six months later, and the new holder silently inherits the previous holder's group memberships and therefore their document access. Nothing in the system can detect this, because from the join's point of view nothing changed.
- Why not: The failure is a silent grant of somebody else's access, which is the exact class of bug this design exists to prevent.

#### Alternative 2: Require an administrator to map identities by hand

- Pros: No weak key anywhere. Every link is a deliberate act.
- Cons: It does not scale past a few dozen people, it has to be redone on every joiner, and an unmapped person is indistinguishable from a mapped person with no access, so the failure mode is the same "product knows nothing" symptom plus manual work.
- Why not: Adopted as the correction path, rejected as the primary path. The administrator API exists precisely to fix links the automatic join got wrong.

#### Alternative 3: Fall back to `tenant:everyone` when a link conflicts, but keep the previously resolved groups

- Pros: Nobody loses access during a reconciliation problem, so no support tickets.
- Cons: It keeps serving group access derived from an identity that may now belong to somebody else. That is the reused-address bug, retained deliberately, with a flag set next to it.
- Why not: A detected conflict has to change behaviour, or detecting it was pointless.

---

### Consequences

- Positive: Split-provider customers work at all, which is the whole point.
- Positive: Address reuse is detectable rather than silent, because a reused address shows the same email against a different provider subject.
- Positive: A broken link degrades to less access, never to more. The person can still sign in and still use the product against generally-shared material.
- Negative: The join key is weak and this decision does not make it strong. It makes the weakness observable.
- Negative: Two identifiers per person per provider is more state to keep correct, and the administrator API to correct it is work that would not otherwise exist.
- Negative: A person with a broken link has no way to tell why their results went quiet, so this failure always routes through support.

#### Risks

- Email normalization differs between providers, so the same person fails to join. Gmail-style dot and plus-tag handling, casing, and unicode domains all differ. Mitigated by one normalization function, applied identically at login and at sync, tested against the specific forms each provider emits.
- Somebody keys the Entra identity on `sub` because the existing [add-auth-and-identity](../../../openspec/changes/add-auth-and-identity/) design uses `sub` as the storage partition key. Mitigated by carrying both claims as separate named fields on the resolved identity object, with `sub` documented as the storage key and `oid` documented as the directory key, so neither can stand in for the other by accident.
