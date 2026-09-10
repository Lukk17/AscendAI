# ADR-010: Logical Tenant Isolation via Mandatory Discriminators

## Status

Proposed, 2026-09-04. Becomes Accepted when the OpenSpec change `add-tenant-isolation` is implemented.

## Context

ascend-ai-agent stores every customer's data in one pool per store. Both Qdrant collections (`ascendai-768` and `ascendai-1536`) hold everyone's chunks, MinIO has one `knowledge-base` bucket keyed by sanitized filename, Redis keys chat history as `chat:{userId}`, and `chat_history` and `user_instructions` carry only `user_id`. Hosting two companies on one deployment means deciding where the boundary between them lives.

There are two shapes available. Separate the infrastructure per customer, so a Qdrant collection, an S3 bucket, a Redis namespace, and a Postgres schema exist per tenant. Or keep the shared infrastructure and put a discriminator on every row, key, and payload, enforced on every read and write.

The same question repeats one level down for the access axis introduced alongside this change, where the units are groups rather than tenants, and there are far more of them.

## Decision

Logical isolation. Shared collections, bucket, Redis instance, and tables, with a mandatory discriminator applied at every read and write path:

- Qdrant: a `tenant_id` payload field on every chunk, and a `tenant_id` equality conjunct in the search filter, with a keyword payload index behind it.
- MinIO: a `tenant/{tenantId}/` key prefix, built from the resolved tenant context and never from user input, checked again before a download is presigned.
- Redis: `chat:{tenantId}:{userId}` and `user:{tenantId}:{userId}:instructions`.
- Postgres: `tenant_id VARCHAR(64) NOT NULL` on the tenant-scoped tables, in the primary key for `user_instructions` and in the composite index for `chat_history`.
- AscendMemory: the composite `user_id` value `{tenantId}:{userId}`, namespacing the partition key that service already uses.

The access axis follows the same shape for the same reason: an `acl` payload field and a set-intersection conjunct, not a collection per group.

## Consequences

- One mechanism covers five stores, so there is one thing to reason about and one class of bug to test for, rather than five provisioning flows that fail differently.
- Adding a tenant is a row in `tenants` and nothing else. No collection to create, no bucket to provision, no schema to migrate, no per-tenant Liquibase run.
- The blast radius of an application bug is wider than under physical separation. A missing discriminator on one path is a cross-tenant read, where separate infrastructure would have made it an error. This is the real cost of the decision and it is paid down with the fail-closed rule in ADR-012, the single search call site in ADR-011, and integration tests that assert cross-tenant reads return zero results.
- Noisy-neighbour effects stay possible: one tenant's large ingest shares index structures and connection pools with everyone else. Acceptable at the scale this platform targets, and revisitable per tenant later without changing the code, since a dedicated deployment is still a deployment of the same image.
- Deleting a tenant becomes a filtered delete across five stores rather than dropping a collection, which matters to `add-audit-and-gdpr-compliance` when it specifies erasure.

### Alternatives considered

Collection, bucket, and schema per tenant. Stronger blast-radius isolation, and a mis-scoped query fails rather than leaking. Rejected because Qdrant collection count would grow with tenants times embedding dimensions, per-request provider routing in `VectorStoreResolver` would need a second dimension, Liquibase would run per schema, and object-store bucket limits bite early. The fail-closed filter gives the same observable guarantee at the scale in question. ADR-M009 rejects the same shape one level down for groups, where the multiplication is worse.

A single tenant per deployment, kept forever. This is today's posture and it is what the change exists to move away from: it blocks consolidating the per-company deployments that already exist, and it prices out any customer smaller than a dedicated stack.

Row-level security in Postgres as the enforcement point. Real and useful for the two Postgres tables, and irrelevant to the three stores that hold the data that actually matters here. Adopting it would mean two enforcement mechanisms with different failure modes and one of them covering the minority of the surface.

## Related

- OpenSpec change `add-tenant-isolation`, design decisions 1, 3, 5, 6, and 7
- ADR-011, which keeps the Qdrant discriminator enforceable by pinning the single search call site
- ADR-012, which defines what happens when the discriminator cannot be resolved
- `docs/architecture/decisions/ADR-M009-enforcement-in-the-agent.md`, which rejects store-level enforcement for the access axis
