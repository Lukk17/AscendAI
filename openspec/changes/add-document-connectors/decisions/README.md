# Decision records for `add-document-connectors`

The monorepo records ADR-M004 through ADR-M009 under `docs/architecture/decisions/` settle permission-aware retrieval as a whole: mirroring access lists onto chunks, filtering inside the vector search, deny-by-default on a missing list, group principals with membership resolved at login, the email join across providers, and enforcement living in the agent.

The records here decide what this change decides on top of that. They follow the format used by `apps/ascend-agent/docs/architecture/decisions/`, and they carry the next free numbers in that directory's sequence at the time of writing.

Five of them were written for a scope that captured per-document access lists from the source. That capture is deferred, because group membership lives in Keycloak alone and no principal this version can mint equals an identifier a file store hands back, so a captured list would match nobody. Those records are marked deferred rather than deleted, with a dated deferral section stating what has to happen for each to become active. Their analysis is intact and returns with the work.

| Record | Status | Decides |
| :--- | :--- | :--- |
| [ADR-010](ADR-010-effective-permissions-not-change-feed.md) | Deferred | Capture reads effective permissions from the source rather than inferring them from the content change feed |
| [ADR-011](ADR-011-container-first-permission-capture.md) | Deferred | Permissions are captured container-first, with per-item reads only where a list is unique or due |
| [ADR-012](ADR-012-dedup-key-content-plus-acl-version.md) | Deferred | The ingestion deduplication key pairs content version with access-list version |
| [ADR-013](ADR-013-payload-only-update-carve-out.md) | Deferred | A permission-only change takes a payload-only vector-store write, carved out of the no-direct-writes rule |
| [ADR-014](ADR-014-access-list-staleness-sweep.md) | Deferred, superseded for this scope by ADR-016 | Access lists past a maximum age are emptied, converting a silent capture outage into visible degradation |
| [ADR-015](ADR-015-sharepoint-first-despite-google-being-cheaper.md) | Proposed, amended | SharePoint stays the first connector although Google Drive is cheaper to make permission-correct |
| [ADR-016](ADR-016-sync-freshness-check-replaces-the-sweep.md) | Proposed | A non-destructive freshness check watches the connector rather than the access list, keeping ADR-014's instinct without its enforcement |

On archive, these move to `apps/ascend-agent/docs/architecture/decisions/` unchanged, taking whatever numbers are free in that sequence at that time and updating this index's links in the same step. A record's status moves from Proposed to Accepted when the change is approved for implementation. A record marked Deferred keeps that status through the archive, because it records a decision the platform has taken and not yet implemented, which is a different thing from a decision nobody made.
