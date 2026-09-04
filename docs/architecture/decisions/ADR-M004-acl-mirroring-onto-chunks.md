# ADR-M004: Mirror Access Lists onto Chunks

---

### Status

Accepted (2026-09-04)

---

### Context

AscendAI answers questions over documents pulled out of SharePoint and Google Drive, where each file already has an access list the source enforces on every open. Once the bytes are chunked, embedded, and stored in Qdrant, that enforcement is gone. `RagRetrievalService` builds its `SearchRequest` from query, `topK`, and a similarity threshold, with no owner predicate of any kind, and `IngestionMetadataKeys` records only `source`, `type`, and `title`.

Restoring the guarantee means the search has to know who may read each chunk. There are two places that knowledge can live: in the source, asked per request, or in the vector store, mirrored at sync.

---

### Decision

Mirror the access list onto every chunk as an indexed payload field, and never ask the source at query time.

Four payload fields per chunk: `acl` (keyword array of permitted principals), `acl_source` (which producer wrote the list), `acl_version` (a stable hash of the sorted list, used as the change-detection key), and `acl_synced_at` (when the list was last confirmed). A keyword payload index on `acl` is mandatory, created in the same migration as the `tenant_id` payload index from [add-tenant-isolation](../../../openspec/changes/add-tenant-isolation/).

---

### Alternatives Considered

#### Alternative 1: Query the source per request

- Pros: Zero staleness. The answer is whatever SharePoint says right now, and there is no capture pipeline to get wrong.
- Cons: A Graph permission call, or several, sits inside the request path before the search can start. It cannot be expressed as a search filter, so it degenerates into post-filtering a candidate list, which is the failure ADR-M005 exists to avoid. It fails whenever the source is down or the credential expired, turning a source outage into a retrieval outage. Graph throttling on a large tenant makes it worse under load, which is exactly when it matters.
- Why not: It cannot be pushed into the vector search, and anything that cannot be pushed into the vector search is a post-filter.

#### Alternative 2: A separate permission service the agent calls before searching

- Pros: One place owns permission logic, cacheable, swappable per customer.
- Cons: It answers "may this person read this document", which still yields a list to filter against rather than a predicate the search can apply. It adds a network hop with its own failure mode inside the request path (see ADR-M009), and it still has to mirror the source's data to be fast, so it is this decision plus a service.
- Why not: Same structural problem as Alternative 1, with an extra deployment unit.

#### Alternative 3: Materialise per-user access into the payload

- Pros: The simplest possible filter, one equality on a user id.
- Cons: Every membership change rewrites the payload of every chunk that group can reach. A person joining a team triggers a mass update across the collection. Storage grows with users times documents rather than groups times documents.
- Why not: Rejected in ADR-M007 for the same reason.

---

### Consequences

- Positive: The permission test becomes a payload predicate, which is the only form that can run inside the vector search rather than after it.
- Positive: Retrieval keeps working when the source is unreachable, because the last confirmed lists are already local.
- Positive: No per-request call to Graph, so no Graph throttling in the answer path.
- Negative: The mirror is stale between syncs. That window is bounded, disclosed, and backstopped by the staleness sweep, but it is real and it is not zero.
- Negative: Roughly 400 bytes per chunk against a 4 to 7.5 kilobyte chunk, so 5 to 10 percent more storage.
- Negative: A capture failure now makes documents invisible rather than merely unsynced, which is the correct direction but is a new class of operator problem.

#### Risks

- Capture stops silently and the mirror freezes at permissions that stopped being true. Mitigated by `acl_synced_at`, an access-list-age metric, and a staleness sweep that empties lists older than a maximum so the failure becomes visible degradation.
- The mandatory payload index is forgotten in a deployment and the filter becomes a collection scan. Mitigated by creating it in the same migration that already creates the `tenant_id` index, so one step owns both.
