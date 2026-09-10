# ADR-011: One Call Site for Similarity Search, Held There by an Architecture Test

## Status

Proposed, 2026-09-04. Becomes Accepted when the OpenSpec change `add-tenant-isolation` is implemented.

## Context

Retrieval is filtered by one expression carrying both isolation axes, `tenant_id == '<currentTenant>' AND acl IN <principalSet>`, composed where the `SearchRequest` is built. That guarantee holds only while there is exactly one place a `SearchRequest` is built. A second retrieval path that assembles its own request is not a partial application of the filter, it is no filter at all on that path, and it looks like an ordinary new feature in a diff.

Today `RagRetrievalService.performSimilaritySearch` is the only production caller of `VectorStore.similaritySearch(...)`. That is a fact about the current code, not a property of it, and nothing prevents the next feature from adding a second one. The failure would be quiet: a developer building a new surface writes a search, tests it against a fixture holding one tenant's documents, sees correct results, and ships a path with neither conjunct on it.

ADR-M009 accepts that permission enforcement living in application code can be bypassed by an application bug, and states that the mitigation is tests rather than architecture. This record is that mitigation, made specific.

## Decision

Exactly one method in production code calls `VectorStore.similaritySearch(...)`, and it is the method that composes the filter expression. An ArchUnit rule, added as a test-scope dependency, asserts that no other production class calls it, and names the offending class when it fails.

A new retrieval surface therefore routes through `RagRetrievalService` and inherits the composed filter, or it changes this rule deliberately and explains why in a new record.

## Consequences

- The mandatory filter becomes enforceable rather than aspirational. A second call site fails the build instead of shipping.
- The failure message points at the class, so the developer who hits it learns why the constraint exists at the moment they hit it rather than in review.
- One test-scope dependency is added, and one more build gate exists that can fail for reasons unrelated to the feature being written. That is the intended cost.
- Legitimate future work is constrained. A surface that genuinely needs a differently-shaped search, for example a metadata-only lookup with no permission relevance, has to either go through the same service or come with a deliberate amendment to this rule. Making that a decision rather than an accident is the point.
- Test code is exempt, since mocks and stubs of `VectorStore` are how the retrieval path is tested at all.

### Alternatives considered

Wrap the vector store in a decorator that refuses a request without a filter expression. Attractive, and weaker than it appears: the decorator can assert that some filter is present, not that it is the right one for this caller, so it enforces the part least likely to be got wrong while adding a bean in front of every provider's store. It also gives a false sense that the check is structural.

Rely on code review. Rejected. The diff that introduces the bug looks like a legitimate feature, and the reviewer would have to remember an invariant that is written nowhere the compiler or the build can see.

Grep the source tree from a plain unit test. Same assertion, written worse, with no type awareness and a habit of breaking on formatting. ArchUnit expresses it directly.

## Related

- OpenSpec change `add-tenant-isolation`, design decision 10, and the `rag-retrieval` requirement "Exactly one method issues the similarity search"
- `RagRetrievalService.performSimilaritySearch`
- ADR-012, the fail-closed rule that covers the case where the one call site runs without resolved context
- `docs/architecture/decisions/ADR-M005-pre-filter-in-vector-search.md` and `ADR-M009-enforcement-in-the-agent.md`
