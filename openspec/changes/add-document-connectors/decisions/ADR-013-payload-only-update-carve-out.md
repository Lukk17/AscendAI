# ADR-013: A Permission-Only Change Takes a Payload-Only Write, Carved Out of the No-Direct-Writes Rule

## Status

Deferred, 2026-09-05. Not implemented by the OpenSpec change `add-document-connectors`, and not accepted by it. This file is the draft that moves into `apps/ascend-agent/docs/architecture/decisions/` on archive with this status intact, taking the next free number at that time.

## Deferral, 2026-09-05

There are no permission-only changes in this version, because there is nothing per document to change, so the carve-out is not taken. The no-direct-vector-store-writes rule holds without exception, the framework interfaces expose no vector store and no embedding client, and the native Qdrant client is not referenced from the connector packages at all.

This is a deferral and not a withdrawal, and the distinction matters more here than in the neighbouring records. The argument this record makes is that a narrow, written, reviewed exception is better than either an unstated one or a rule that forces an hour-long revocation. Marking it withdrawn would leave the next person who needs a payload write with a rule and no precedent, which is how an unstated exception gets invented. Marking it deferred leaves them a reviewed limit: four keys, four prohibitions, one tenant predicate.

Nothing below was found to be wrong. The observable that proves no re-embed happened, unchanged point identifiers, is the one an implementation cannot fake, and it is asserted in this version too, on the re-enumeration path where an unchanged file must keep its points.

What has to happen for this record to become active: a permission-only change has to be possible, which means ADR-010 and ADR-012 becoming active.

## Context

The connector framework states a firm rule: a connector lands bytes and triggers the existing pipeline, and it never writes to the vector store directly. The rule earns its place. One write path means one set of parser bugs, one dedup semantics, one metrics surface, and no way for a connector to produce chunks the ingestion pipeline never saw.

ADR-012 makes permission-only changes visible to that pipeline. What the pipeline then does with one is the problem.

The pipeline's only tool for changing a chunk is to re-index the document: re-parse, re-chunk, re-embed, replace. For a 200-chunk document whose sharing changed and whose text did not, that is 200 embedding calls to rewrite one keyword array. It costs money for a change that produced no new meaning, and it costs time: a revocation that should land in seconds instead takes as long as re-embedding the document, and for that whole window the revoked group can still retrieve it. The slowest possible response to a revocation is the one the architecture would force.

Spring AI's `VectorStore` abstraction cannot help. It offers `add` and `delete`, and `add` means embed. There is no payload update operation to reach for.

So either the rule bends here, or a revocation takes an hour.

## Decision

A permission-only change takes a payload-only update, using the native Qdrant client's `setPayload` against the points that already exist for that source, and this is an explicit carve-out in the framework's no-direct-writes rule rather than an unstated exception.

The carve-out is narrow and the narrowness is the whole argument for it. The path may set exactly four keys: `acl`, `acl_source`, `acl_version`, `acl_synced_at`. It may not create a point, may not delete a point, may not alter any other payload key, and may not trigger embedding. It carries the same tenant predicate every other vector-store operation carries.

The native Qdrant client is already a declared dependency as `libs.qdrant.client` in `apps/ascend-agent/build.gradle.kts`, so this is a second and narrower use of something already present, not a new dependency.

## Consequences

### Why an explicit carve-out rather than a quiet exception

A rule with an undocumented exception is worse than a rule with a documented one, because the next person to need an exception finds precedent rather than a boundary. Writing the carve-out into the spec, with its four permitted keys enumerated and its four prohibitions enumerated, means the next proposed exception has to argue against a written limit instead of pointing at an existing violation.

Naming the keys explicitly rather than replacing the payload also closes a specific failure: a payload replacement that forgot `tenant_id` would silently strip the tenant predicate off a chunk, which under a fail-closed filter makes the chunk invisible and under a permissive one makes it cross-tenant. A four-key `setPayload` cannot do either by omission.

### Trade-offs

- Two things can now write to the vector store, and one of them is not the ingestion pipeline. That is a genuine loss of the single-writer property, mitigated by scope rather than by architecture, and the mitigation is tests.
- The framework's dependency on Spring AI's abstraction is no longer total. Where the abstraction is insufficient, the native client is used, which means two mental models for how a chunk gets modified.
- The path assumes points for that source already exist. When they do not, it writes nothing, which is correct, and is asserted rather than assumed.
- Correctness of "no re-embed happened" is provable only by an observable that is a little indirect: the point identifiers are unchanged. That is the assertion the tests make, because it is the one an implementation cannot fake by re-embedding into the same ids.

### Alternatives considered

- **Re-index the document like any other change.** The option that preserves the rule intact. Rejected on the numbers: 200 embedding calls to change one field, an hour-long window during which a revocation has not taken effect, and a bill for a change that touched no text. The rule is not worth that.
- **Delete and re-add the document's chunks.** Available through the existing abstraction. Rejected because `add` means embed, so this is the previous option with an outage in the middle: the document is unretrievable by everybody while the re-add runs.
- **Route the payload update through the ingestion pipeline as a new operation type.** Keeps one writer. Rejected as the more invasive change: it means teaching the ingestion path a concept it has no other use for, in service of a purity argument, when the carve-out expresses the same limit in a spec paragraph.
- **Store the access list outside the vector store and join at query time.** Would remove the need to update payloads at all. Rejected upstream by ADR-M005: anything not in the payload cannot be a pre-filter, and a post-filter is the failure that decision exists to prevent.

## Related

- ADR-M005 (`docs/architecture/decisions/ADR-M005-pre-filter-in-vector-search.md`) for why the list has to be in the payload
- ADR-012, which makes these runs happen at all
- ADR-011, for the container revocation that fans out into many of these updates
- Design decisions D11 and D1
