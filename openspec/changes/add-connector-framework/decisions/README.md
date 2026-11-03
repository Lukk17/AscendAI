# Decision records for `add-connector-framework`

The records here decide what this change decides on top of the monorepo records ADR-M004 through ADR-M009 under `docs/architecture/decisions/`. They follow the format used by `apps/ascend-agent/docs/architecture/decisions/`. They carry no number yet. Each file is named `ADR-NNN-<slug>.md` and takes the next free number in that directory's sequence at implementation time.

| Record | Status | Decides |
| :--- | :--- | :--- |
| [sync-freshness-check-replaces-the-sweep](ADR-NNN-sync-freshness-check-replaces-the-sweep.md) | Proposed, moved here from `add-document-connectors` on 2026-10-04 | A non-destructive freshness check watches the connector rather than the access list, keeping the instinct of the `access-list-staleness-sweep` record of `add-document-connectors` without its enforcement |

On archive, the record moves to `apps/ascend-agent/docs/architecture/decisions/` unchanged, taking the next free number at that time. The same step replaces `NNN` in the file name and title and updates this index's link.
