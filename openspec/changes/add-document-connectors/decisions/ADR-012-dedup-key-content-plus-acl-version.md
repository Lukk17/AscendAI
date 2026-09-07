# ADR-012: The Deduplication Key Pairs Content Version With Access-List Version

## Status

Deferred, 2026-09-05. Not implemented by the OpenSpec change `add-document-connectors`, and not accepted by it. This file is the draft that moves into `apps/ascend-ai-agent/docs/architecture/decisions/` on archive with this status intact, taking the next free number at that time.

## Deferral, 2026-09-05

A connector-landed document's access list in this version is `tenant:everyone:{tenantId}` and nothing else, stamped by the ingestion producer rather than captured from the source, so its version is a constant. Pairing a constant into the deduplication key would add a segment that never varies and a second marker format that never earns its keep. The connector-landed marker therefore stays `manual-ingestion:<key>:<etag>`, byte-identical to the manual upload path's, and this change requires that there be no second format anywhere in the connector packages.

Nothing below was found to be wrong. Two of its findings survive the deferral and are worth reading before the pairing returns: that the sort is what makes the version mean "the permitted set changed" rather than "the response was ordered differently", and that a hash bug presents either as constant spurious updates or as missed revocations and therefore needs its own tests rather than trust.

The paragraph in the Context section about the current spec writing the content-only bug into a requirement no longer applies as written. The scenario it named asserted that an unchanged file re-landed is a no-op, which under a captured list would have prescribed the bug and which under a company-wide list is simply correct. It becomes a defect again the day capture returns, which is why the paragraph stays.

What has to happen for this record to become active: an access list whose value can differ between two runs of one connector, which means ADR-010 becoming active.

## Context

`ManualIngestionService` skips an object when a marker already exists for it, and the marker is `manual-ingestion:<key>:<etag>`. The ETag is a hash of the bytes. Unchanged bytes produce an unchanged ETag, which produces a marker hit, which produces a skip.

That is correct behaviour for a pipeline whose only concern is content, and it is the pipeline this change reuses deliberately, because one dedup semantics is worth keeping.

It stops being correct the moment a chunk carries an access list. Somebody revoking a group's access to a document does not touch the bytes. A permission-only change is by definition an unchanged file, so under a content-only key the single most common permission event in any real company produces a marker hit and is skipped. The revocation is never seen, and the document keeps serving its old list until something unrelated edits it, which for a policy document may be never.

The current `add-document-connectors` spec does not merely inherit this. It writes it into a requirement, in a scenario asserting that an unchanged file re-landed is a no-op with the Qdrant chunk count unchanged. Read as a statement about embeddings that is correct and desirable. Read as a statement about the whole sync outcome, which is how it is written, it prescribes the bug.

## Decision

The deduplication key for a connector-landed object becomes the pair of content version and access-list version: `manual-ingestion:<key>:<contentVersion>:<aclVersion>`.

`contentVersion` is the ETag, unchanged from today. `aclVersion` is a stable hash of the sorted principal list. A change to either produces a distinct key, so a permission-only change is processed and a genuine no-op is still skipped. The marker format for objects landed by the manual upload paths is untouched.

The hash is taken over a canonical form: principals sorted lexicographically and joined with a separator the principal format cannot contain.

## Consequences

### Why the sort matters more than it looks

Sorting is what makes the version mean "the effective permitted set changed" rather than "the source's response differed". Sources do not promise a stable order, so an unsorted hash would change on a response reordering, every reordering would present as a permission change, and every such change would trigger a payload write on a document nothing happened to. The counter that is supposed to say "permissions moved" would then say it constantly and stop being a signal.

Sorting also makes two items sharing a permitted set share a version, which is what turns the container-level comparison in ADR-011 into a single equality instead of a set difference over two lists.

### Trade-offs

- A permission-only change now costs a marker write and a payload write on a run that would previously have done nothing. That is the cost of noticing, and it is small next to the alternative.
- The key is longer, and it encodes a second thing that can be computed wrongly. A bug in the hash presents as either constant spurious updates or as missed revocations, so the hash gets its own tests rather than being trusted as an implementation detail.
- Two dedup key formats now exist in the system, one for connector-landed objects and one for manually uploaded ones. Deliberate: extending the manual format would change behaviour on a path this change is not otherwise touching, and manual uploads have no access-list source to hash.
- A hash collision between two genuinely different lists would silently skip a real permission change. The hash is chosen wide enough that this is not a practical concern, and the collision property is asserted over a generated corpus rather than assumed.

### Alternatives considered

- **Keep the content-only key and detect permission changes separately, outside dedup.** Plausible, and it keeps one key format. Rejected because it puts two mechanisms in charge of deciding whether an item needs processing, and the first one to say "skip" wins. The dedup key is the gate, and a change that must not be skipped has to be visible to the gate.
- **Force-process every item every run and let downstream comparison decide.** Correct and wasteful: it discards the dedup mechanism entirely and re-downloads content that has not changed.
- **Store the access-list version only in the connector's own table and compare there, leaving the marker alone.** This is close to what happens anyway, and it was rejected as the sole mechanism rather than as an addition. The connector-side record is an optimisation that can drift, while the marker is the thing the ingestion scan actually consults, so if the marker says skip, nothing downstream gets a vote.
- **Include `acl_synced_at` in the key.** Rejected immediately: the timestamp changes on every confirmation, so every confirmation would present as a change and every document would be reprocessed on every run.

## Related

- `docs/architecture/permission-aware-retrieval.md`, "Failure mode one: the permission-only change"
- ADR-013, for what happens on the runs this key stops skipping
- ADR-011, which relies on a shared version being a single equality
- Design decision D10
