# ADR-011: A Principal Set Is Never Silently Narrowed

## Status

Proposed, 2026-09-04. Amended 2026-09-04, see Amendment below. Accepted when the OpenSpec change `add-auth-and-identity` lands. This file is the draft that task 12.8 installs into `apps/ascend-agent/docs/architecture/decisions/`, taking the next free number at that time.

## Amendment, 2026-09-04

The rule stands unchanged: no path that cannot produce a caller's true principal set may produce a quietly small one. Its scope narrowed on the day it was written, because group membership now comes from Keycloak realm groups alone and there is no directory call to fail.

Two of the three numbered decisions below are in scope for this change and unchanged. A resolved set over the cap fails with 403 and never truncates. The `dev` profile synthesises `tenant:everyone:default` and `local:group:dev-all` and never an empty set.

The first, the 503 on a failed directory call, has nothing to apply to yet. It is deferred with the directory work, its reasoning is preserved below and in the change's design document, and it returns unchanged the moment a directory lookup does. Nothing about it was found to be wrong.

One new path is worth naming, because it looks like a narrowing and is not. A token carrying no group claim now resolves to no group principals, and that is a true statement about an administrator having placed the caller in no groups rather than a silence to be suspicious of. Under the previous design an absent claim could mean an over-cap user whose groups were dropped, which is why it had to fall through to a directory rather than be believed. With Keycloak as the only source, the claim is authoritative and believing it is correct.

The other silent-narrowing risk this change introduces in place of the old one is a group name an administrator chose that breaks the principal character set. The factory throws rather than mangling it, so it fails loudly, which is the same rule reaching a new surface.

## Context

Under `docs/architecture/permission-aware-retrieval.md` a caller retrieves a chunk only when the chunk's access list contains a principal the caller holds, and a chunk with no list is retrieved by nobody (ADR-M006). The principal set is therefore the whole of a person's read access, and a set that is smaller than the truth is indistinguishable, from outside, from a corpus that does not contain the answer.

That matters more than it first sounds, because the symptom of a narrowed set is not an error. It is a 200 response, a fluent answer, and no sources. The person who reports it says search is broken. The engineer who investigates it looks at chunking, at the embedding model, at the similarity threshold, at the reranker, and at the prompt, because all of those produce the same symptom. Nothing points at authorization, because authorization succeeded.

ADR-M007 already refuses one version of this: a resolved set over the cap fails the request rather than being truncated. It does not cover the other two ways a set can come out small.

The first is upstream failure. Microsoft Graph throttles, a client secret expires, a directory is briefly unreachable, and the cache misses. The tempting answers are to fall back to `tenant:everyone:{tenantId}` so the person can still use the product, or to serve the cached set past its time to live so the blip is invisible.

The second is the development profile. It synthesizes an identity so there is one identity code path, and the smallest thing it can synthesize is an empty principal set. A developer then runs the stack locally, ingests a corpus, asks it a question, and gets nothing.

## Decision

Every path that cannot produce a caller's true principal set either fails loudly or produces a deliberate, documented one. None of them produces a quietly small one.

1. A directory call that fails, for any reason, fails the request with HTTP 503 and a `Retry-After` header. There is no fallback to the tenant floor, and a cached principal set is never served past its time to live.
2. A resolved set exceeding the configured cap of 256 fails the request with HTTP 403 and an `application/problem+json` body naming the cap and the resolved size, per ADR-M007. It is never truncated to fit.
3. The `dev` profile synthesizes `tenant:everyone:default` and `local:group:dev-all`, never an empty set, and `docs/SECURITY.md` states that a locally-ingested corpus must carry one of those two principals to be retrievable.

## Consequences

### Why this way

- A 503 is a page for whoever runs the deployment, and it names its own cause. A narrowed set is a week of somebody bisecting the retrieval pipeline for a bug that is not there.
- The failure lands on the operator rather than on the user's mental model of the product. A customer who sees an explicit outage keeps trusting the answers they got yesterday. A customer whose search quietly went shallow stops trusting all of them, and there is no way to tell them afterwards which answers were affected.
- The development profile becomes a real environment rather than a demonstration of deny-by-default. A developer can seed a corpus and retrieve it, which is the only way the permission path gets exercised locally at all.

### Trade-offs

- Directory availability becomes product availability on the cache-miss path. This is the real cost and it is accepted rather than argued away. The Redis cache from ADR-M007 absorbs a short outage for anybody recently active, so the blast radius is cold callers during the outage window, not everybody.
- The design document's open question about synchronous membership resolution against a large directory stays open, and this decision makes the consequence of a slow or failing directory more visible rather than less. That is intentional: the measurement does not exist yet, and hiding the failure would remove the pressure to take it.
- A person legitimately in more than 256 groups cannot use the product until an administrator changes the cap. Accepted, because the alternative is that person quietly losing access to some of their documents with no indication which ones.
- The dev principal set is one more thing that has to stay in step with what the dev-profile ingestion path writes. If they drift, local retrieval goes quiet, which is the exact symptom this record exists to prevent, arriving through the back door. Mitigated by stating both values in `docs/SECURITY.md` and asserting them in a slice test.

### Alternatives considered

- Fall back to `tenant:everyone:{tenantId}` when the directory is unreachable. Pro: nobody is locked out, no support tickets during a Graph incident. Con: every affected person silently loses access to everything except tenant-wide material, for an unbounded period, with a 200 on every request. Rejected because it converts a bounded, diagnosable outage into an unbounded, undiagnosable degradation.
- Serve the cached principal set past its time to live during a directory outage. Pro: invisible to almost everyone, and the set is probably still correct. Con: it is the revocation window from the staleness table, extended by exactly as long as the outage lasts, with nothing bounding it and no signal that it happened. A membership revocation is one of the two events the five-minute cache exists to bound. Rejected.
- Degrade only the retrieval path and let chat continue without RAG. Pro: the product stays partly usable. Con: an answer with no retrieved context looks exactly like an answer where retrieval found nothing, so this is the silent narrowing again with an extra branch. Rejected.
- Let the dev profile synthesize an empty set and require developers to configure principals. Pro: no magic values, and the local path matches production exactly. Con: the first experience of every developer is a corpus that answers nothing, and the fix is not discoverable from the symptom. Rejected in favour of two documented values.

## Related

- `docs/architecture/permission-aware-retrieval.md`, sections "Resolving group membership", "Staleness", and "Observability, honestly"
- `docs/architecture/decisions/ADR-M006-deny-by-default-on-missing-acl.md`
- `docs/architecture/decisions/ADR-M007-group-principals-membership-at-login.md`
- OpenSpec change `add-auth-and-identity`, decisions D5, D9, D10 and D14, and the Deferred D14a entry that carries the directory-failure rule, capability `principal-resolution`
