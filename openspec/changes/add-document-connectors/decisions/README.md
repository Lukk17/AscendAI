# Decision records for `add-document-connectors`

The monorepo records ADR-M004 through ADR-M009 under `docs/architecture/decisions/` settle permission-aware retrieval as a whole: mirroring access lists onto chunks, filtering inside the vector search, deny-by-default on a missing list, group principals with membership resolved at login, the email join across providers, and enforcement living in the agent.

The records here decide what this change decides on top of that, in the capture half. They follow the format used by `AscendAgent/docs/architecture/decisions/`, and they carry the next free numbers in that directory's sequence at the time of writing.

| Record | Decides |
| :--- | :--- |
| [ADR-010](ADR-010-effective-permissions-not-change-feed.md) | Capture reads effective permissions from the source rather than inferring them from the content change feed |
| [ADR-011](ADR-011-container-first-permission-capture.md) | Permissions are captured container-first, with per-item reads only where a list is unique or due |
| [ADR-012](ADR-012-dedup-key-content-plus-acl-version.md) | The ingestion deduplication key pairs content version with access-list version |
| [ADR-013](ADR-013-payload-only-update-carve-out.md) | A permission-only change takes a payload-only vector-store write, carved out of the no-direct-writes rule |
| [ADR-014](ADR-014-access-list-staleness-sweep.md) | Access lists past a maximum age are emptied, converting a silent capture outage into visible degradation |
| [ADR-015](ADR-015-sharepoint-first-despite-google-being-cheaper.md) | SharePoint stays the first connector although Google Drive is cheaper to make permission-correct |

On archive, these move to `AscendAgent/docs/architecture/decisions/` unchanged, taking whatever numbers are free in that sequence at that time and updating this index's links in the same step. Their status moves from Proposed to Accepted when the change is approved for implementation.
