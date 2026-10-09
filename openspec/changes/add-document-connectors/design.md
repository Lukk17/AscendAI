## Context

The connector framework moved to `add-connector-framework` on 2026-10-04 (owner rule of 2026-10-04: the personal assistant comes first, nothing personal may depend on company work, and company work comes last and only plugs in through extension points with safe defaults). That change is personal work of build group 4. It holds the framework decisions D1 to D3, D5 and D19 to D23 with their numbers, the run history, the freshness check, the `/api/v1/connectors` API, `docs/CONNECTORS.md`, and the `ConnectorCredentialStore` port with its own encrypted store (its D24). Its tenant prefix comes from its `TenantPrefixResolver` port (its D25), whose default answers the empty prefix and for which `add-tenant-isolation` registers the `tenant/{tenantId}/` implementation, the tenant itself comes from `TenantContext.currentTenantId()` of `add-keycloak-login` (tenant `default` in a personal deployment), and its `ADMIN` rule is its row in the matrix of `add-keycloak-login`. This change is build group 5, position 7 of the owner build order of 2026-10-04, after `add-connector-framework`, `add-auth-and-identity` and `add-tenant-isolation`.

This change is the company half. It adds the first company connector type, SharePoint and OneDrive through Microsoft Graph, which is where EU corporate documents actually live, the rules for the access list a connector-landed document carries, and the deferred design for capturing per-document permissions from the source. It plugs into the framework as one more connector type and edits no framework class.

Permission-aware retrieval is settled design, recorded in `docs/architecture/permission-aware-retrieval.md` and in ADR-M004 through ADR-M009 under `docs/architecture/decisions/`. That design splits into three halves: a verified caller with resolved group principals (`add-auth-and-identity`), a filter composed into the vector search over an `acl` payload field (`add-tenant-isolation`), and the capture of that `acl` field from a real source at sync time. The third half was this change's, and it is the half this version does not deliver.

The scope of this change has been cut to match the authentication scope the owner settled. Groups live in Keycloak and nowhere else. Nothing is read from a customer's Microsoft or Google directory, and `add-auth-and-identity` mints principals only in the `local` and `tenant` namespaces. A SharePoint permission entry names an Entra ID directory object id, which is a principal in a namespace this version cannot mint and which the typed factory rejects. So capturing per-document permissions from the source is not merely unimplemented here, it is unrepresentable, and a connector that tried would fail capture on every item and land nothing.

For this version, therefore, a document a connector syncs is visible to everyone in the company. It carries `tenant:everyone:{tenantId}` and nothing else, and it is what `add-auth-and-identity` states as a named limitation on its side. D18 is that decision and the Named limitation section below states it in customer terms. The capture design is not deleted. It is preserved whole in the Deferred section, because the moment a customer with a real directory arrives it returns as written.

Dependencies on sibling changes (their scope is not re-specified here):

- `add-connector-framework`: the framework this change adds the `SHAREPOINT` type to: `DocumentConnector`, the orchestrator, the landing contract, scheduling, run history, the freshness check, the API with its `ADMIN` row, `ConnectorCredentialStore` and `TenantPrefixResolver`.
- `add-auth-and-identity`: the principal format and the tenant claim of a company deployment. It does not provide a directory identifier, a directory-namespaced principal, or a cross-provider identity link in this version, and nothing in this change depends on one.
- `add-tenant-isolation`: the tenant prefix implementation of `TenantPrefixResolver`, the tenant metadata carried into Qdrant chunks, the `acl`, `acl_source`, `acl_version` and `acl_synced_at` metadata keys, the mandatory keyword payload index on `acl`, the `tenant:everyone:{tenantId}` pseudo-group, the ingestion producer default that stamps it, and the filter composition that reads all of it.
- `add-document-management-api`: the document registry and the single-document deletion machinery the framework calls.

## Goals / Non-Goals

Goals:

- SharePoint and OneDrive via Microsoft Graph as a connector type of `add-connector-framework`, with client-credentials auth, delta-query incremental sync, site, drive and folder scoping, allowlist-aligned file filtering, and Graph-compliant throttling behaviour.
- Every connector-landed document is retrievable by the company that owns it, through the tenant-everyone grant the ingestion producer already stamps, so a sync that reports success produces documents that answer.

Non-Goals:

- Everything the framework holds (`add-connector-framework`).
- Per-document access-list capture from the source. Deferred whole, with its analysis, in the Deferred section. The consequence is stated in the Named limitation section rather than softened.
- Google Drive, Confluence, and network-share connectors. Named follow-ons, explicitly out of scope. The framework interfaces make each of these an additive implementation plus a Flyway migration that admits the new enum value. See D17 for the ordering argument and what changed about it under this scope.
- Real-time (webhook or subscription based) change notification from Graph. First iteration is polling via scheduled delta sync. Graph change notifications are a later optimisation.
- The retrieval side of permission-aware retrieval. Composing `acl` into the `SearchRequest`, the deny-by-default rule for a chunk with no list, the payload index, the metadata key definitions, and the presign re-check all belong to `add-tenant-isolation`.
- Composing an access list at all. `add-tenant-isolation` owns the one place that mints `tenant:everyone:{tenantId}` and stamps the four access-list keys, and this change consumes that rather than writing a second producer of the same value (D18).
- Group membership resolution, the principal identifier format and its factory, and the cross-provider identity link. All `add-auth-and-identity`.
- User-delegated (on-behalf-of) Graph auth. Client credentials only.

## Decisions

Decision numbers are stable. D1 to D3, D5 and D19 to D23 moved to `add-connector-framework` on 2026-10-04 with their numbers, so a cross-reference to them now lands there. A decision that has been deferred keeps its number and moves to the Deferred section, so a cross-reference from a sibling change or a decision record still lands on the right text.

### D3b: The `SHAREPOINT` type joins the framework's data model

This change adds a Flyway versioned SQL migration `V<n>__connector_type_sharepoint.sql` (`<n>` the next free version at implementation time) that replaces the named check constraint on `connector.type` of `add-connector-framework` D3 to admit `SHAREPOINT` next to the values already admitted. The framework's per-cursor discriminator holds the Graph drive id, because Graph issues one delta token per drive. No other table changes.

### D4: SharePoint sync via Graph delta queries

- Auth: MSAL-style client-credentials flow per tenant (Entra ID app registration; tenant id + client id + encrypted client secret in the credential store). Token cached in memory until expiry; never persisted, never logged.
- Change detection: `GET /drives/{drive-id}/root/delta` (scoped to configured folders by filtering returned paths). First run is a full enumeration (delta with no token); subsequent runs pass the stored `deltaLink` token and receive only created/modified/deleted items. Deleted items arrive as entries with a `deleted` facet.
- Scoping: configured sites are resolved to drives via `GET /sites/{site-id}/drives`; folder scoping filters delta results by path prefix. Items outside scope are ignored (not recorded as skipped, they are not part of the connector's universe).
- Filtering: file MIME (from Graph item metadata, re-verified by Tika sniff before the object storage write per `add-connector-framework` D1) must be in `app.ingestion.upload.allowed-mime-types`; file size must not exceed the connector's size limit, the setting `app.connector.sharepoint.max-file-size`, which when unset takes the upload limit `spring.servlet.multipart.max-file-size` from `ingestion-security`, so the two stay aligned (owner answer 98, task 2.9). Filtered files are recorded as `SKIPPED` with reason.
- Throttling: on HTTP 429 or 503 with `Retry-After`, sleep the advised interval; without the header, exponential backoff with jitter, bounded retries per request and a bounded total-throttle budget per run, each a setting under `app.connector.sharepoint.throttle.*` (owner answer 98, task 2.9). Exceeding the budget ends the run as `PARTIAL` with the cursor unadvanced past the completed window. This follows Microsoft's published throttling guidance for Graph.

One throttling budget, not two. The separate permission budget is deferred with the permission reads it protected (Deferred D8, Deferred D9), and it returns with them, because the argument for splitting the budget was that a permission storm must not starve document landing and there are no permission requests to storm.

*Why delta queries over full listing + diff:* delta is the Graph-native incremental mechanism, server-side change tracking, one round trip per page of changes, deletions included. Full listing per sync would hammer both Graph (throttling) and our comparison logic, and cannot see deletions without keeping a full remote-inventory shadow ourselves.

*What delta does not do:* it does not reliably report a permission change on an item whose content did not change, and it does not report a permission change made higher in a folder tree as a change on each descendant. That was Deferred D8's problem and it is not a problem this version has, because this version reads no permissions. It becomes one again the day capture returns, which is why Deferred D8 is kept rather than dropped.

### D6: Credentials: reference, not value

The Entra ID tenant id, client id and client secret of a SharePoint connector are stored through the `ConnectorCredentialStore` port of `add-connector-framework` (its D24), and the `connector` row holds only the opaque reference. `SHAREPOINT` declares that it needs a credential, so a create without one is refused by the framework. API responses never echo secrets (write-only field), and logs and sync-run records carry the reference only. Rotating a secret is an update through the store with no connector-table change. `add-usage-metering-and-quotas` keeps its BYOK provider keys in this same store and registers no store of its own (its D8, owner answer 89.9), so this change needs no edit.

### D15: Application permissions wide enough to read content, and no wider

The Azure app registration a customer administrator creates needs content grants and nothing else in this version.

Microsoft's reference for reading a `driveItem` gives, for application permission type, `Files.Read.All` as a least-privileged permission and `Sites.Read.All` among the higher-privileged alternatives. `Sites.Read.All` is what this change asks for, because that one grant covers site enumeration, drive enumeration, and item content. `Sites.Selected` is the genuinely least-privileged alternative and is noted in the setup guide, with the caveat that it is granted per site by an administrator and that a site added to a connector's scope without that grant fails to sync rather than syncing empty.

The directory group read grant, `GroupMember.Read.All`, is not requested and is not needed. It existed to resolve a permission entry's group identity into a principal, and there is no principal mapping in this version. Removing it from the onboarding is a real reduction in what a customer is asked to consent to: an application identity that can read a company's documents is a smaller ask than one that can also enumerate their directory groups, and this change should not ask for the second while it cannot use it. The analysis of why the content grants do not cover directory reads, and of the short-list failure mode that made the distinction load-bearing, is preserved in Deferred D15a.

### D17: SharePoint stays the first connector

SharePoint is the first connector. Google Drive, Confluence, and network shares remain named non-goals.

The reasoning that put SharePoint first is that the customers this is being built for are on Microsoft, and it is unaffected by the scope cut.

Correction (owner decision 65.8 of 2026-10-04): the counter-argument below is wrong for shared drives. The Drive v3 File reference says `permissions[]` is "Not populated for items in shared drives", so a Google Drive connector needs one `permissions.list` call per file in a shared drive, the same per-item cost as Graph. The paragraph is kept as the record's history. The counter-argument this decision used to weigh against, that Google Drive is cheaper to make permission-correct because its change feed returns permissions inline while Graph needs a separate request per item, is dormant rather than resolved. Under this scope neither connector reads permissions, so the two are equally cheap and the ordering question has one input rather than two. The argument returns intact the day capture returns, and it is recorded in the `sharepoint-first-despite-google-being-cheaper` record and in Deferred D9 rather than in this decision, so that a future reader re-opening the ordering finds the analysis rather than rediscovering it.

### D18: A connector-synced document is visible company-wide, and the connector composes no list itself

Every chunk produced from a connector-landed document carries `acl` of exactly `["tenant:everyone:{tenantId}"]`, `acl_source` of `tenant-default`, the matching `acl_version`, and `acl_synced_at` set at ingestion. That is the same stamp `add-tenant-isolation` already applies to a document with no source-captured list, applied by the same ingestion producer, and the connector supplies no list of its own.

Three things follow from the connector composing nothing, and each is the reason rather than a consequence.

There is one producer of `tenant:everyone:{tenantId}` in the system. `add-tenant-isolation` owns the helper that builds it, validates it against the principal format, and computes its version. A connector that assembled the same value would be a second implementation of one piece of knowledge, and the failure mode of a divergence is not a compile error, it is a chunk whose list is syntactically valid and matches nobody.

`acl_source` says `tenant-default` and not `sharepoint`, because the list did not come from SharePoint. An `acl_source` of `sharepoint` on a list nothing at SharePoint decided would be a lie told in a payload field an operator uses to answer "where did this grant come from", and the day capture lands it would be indistinguishable from a genuinely captured list. Whether a document arrived through a connector is answerable from its object key and its document metadata, which is where that question belongs.

The connector framework therefore has no access-list code path at all in this version, rather than a stubbed one. There is no capture interface with a company-wide implementation, no cap check that can never fire, and no version comparison whose two sides are always equal. Machinery that cannot fail is machinery whose tests prove nothing, and it is worse than absent, because the next reader takes its presence as evidence that capture works.

What this costs is stated plainly in the Named limitation section rather than buried here: a customer whose SharePoint has genuinely restricted material gets coarser access in AscendAI than they have at the source.

## Named limitation: connector-synced documents are company-visible in this version

This is the one place where the scope cut changes what a customer gets, rather than only what we build, and it is written out here rather than softened into a caveat. It is the same statement `add-auth-and-identity` makes from the identity side, and the two say the same thing on purpose. It applies to every connector type once `add-tenant-isolation` stamps access lists, the `OBSIDIAN` type of `add-obsidian-vault` included, and this change is where the rule lives.

A document synced from a customer's own storage is readable in AscendAI by everyone in that company, regardless of who could open it in SharePoint. A connector reads no permissions and captures no access list.

The reason is not that capture is hard. It is that capture has nothing to produce. SharePoint names an Entra ID security group by its directory object id, and this version mints principals only from Keycloak realm groups in the `local` namespace. A Keycloak group name will never equal an Entra directory object id, so a captured list would match nobody, for everybody, always, and under deny-by-default every synced document would be invisible to the entire company. That is the worse of the two honest options: the sync reports success, the storage bill arrives, and nothing can be retrieved.

Per-document permissions are reachable in this version only for documents uploaded directly into the product, where the groups on a document and the groups in a caller's principal set are both Keycloak realm groups and can therefore match. The identity and retrieval halves of that are complete: the factory mints `local:group:*`, the filter matches on it. The surface an administrator uses to assign those groups to an uploaded document is `PUT /api/v1/documents/{id}/access` of `add-tenant-administration` (its D8), which lands before this change with the retrieval groups of its D7. A direct upload lands on the tenant-everyone grant until an administrator narrows it there. The mechanism works there and cannot work for a connector-synced document.

What would have to be built to lift it, which is analysis already done and preserved in the Deferred section below rather than deleted:

- Directory group identifiers have to reach the agent, which is deferred on the identity side.
- The principal namespaces `entra` and `google` have to be added to the closed set the typed factory validates against.
- A person's Keycloak identity has to be connected to their identity at the directory whose groups the access lists name, which is the cross-provider identity link, deferred on the identity side.
- And the owner's open decision has to be taken: how a customer's directory groups relate to Keycloak's, whether they are imported, mirrored, mapped by an administrator, or bypassed by resolving membership at the directory.

Until then, the honest statement to a customer is that every document a connector syncs is readable by their whole company, and that group-level restriction is available only on the direct-upload path, through `PUT /api/v1/documents/{id}/access` of `add-tenant-administration` (its D8).

## Deferred

Everything in this section was designed, checked against primary sources, and then taken out of scope by the decision that groups live in Keycloak only. None of it is wrong. It is not needed until a connector can produce a principal a caller might actually hold, and it is kept here because re-deriving it would cost more than reading it.

Every deferred decision keeps its number. A sibling change or a decision record that cross-references D9 or D11 still lands on the right text.

### Deferred D3a: The `connector_item_acl` table

`connector_item_acl`: connector FK, source item id, object key, `acl_version`, `acl_synced_at`, the container id the list was inherited from (nullable, D9), and the captured principal list. This is the connector-side record of what was last written onto that item's chunks. It exists so the four-way branch in D11 can compare against a stored value without reading Qdrant per item, and so the staleness sweep in D14 has something cheaper than the vector store to scan.

*Why a connector-side access-list record at all:* the authoritative copy of an access list is the chunk payload in Qdrant, and it stays that way. Reading it back per item per run would mean a Qdrant round trip for every file in a large drive on every sync, on the sync path, to answer a question a local row answers for free. The row is a cache of what was written, reconciled by the sweep, and the sweep is what catches it drifting.

### Deferred D7: Access-list capture is per in-scope item, and it is not optional

Every item a connector lands carries a captured `AccessList`. The list is the set of principals permitted to read it, expressed in the `namespace:type:id` format from `add-auth-and-identity` and produced through that change's typed factory, never by string concatenation here.

The captured list is written by the framework onto the chunk metadata for that item, populating the four keys `add-tenant-isolation` defines: `acl` (the sorted principal set), `acl_source` (which connector produced it, for example `sharepoint`), `acl_version` (the hash defined in D10), and `acl_synced_at` (the epoch second at which the source was asked, not the second at which the list last changed).

Two rules make the field trustworthy rather than merely present.

Capture failure fails the item. If the source refuses the permission read, returns a permission collection the connector cannot interpret, or returns a partial collection because the granted application permission is too narrow to see all of it, the item's outcome is `FAILED` with the capture reason. No chunk is indexed for it, and bytes already landed for it in this run do not trigger ingestion. An item that is invisible because capture failed is a line in the run history with a file name on it. An item that is invisible because an empty list was written silently is a support ticket about search finding nothing.

An empty list and a failed capture are different things and must never be conflated. A source can legitimately report that no group may read an item, and that is an empty list, deliberately written, making the item invisible to group-based retrieval by design. A source that refused to answer produced no list at all. The first is `ADDED` with an empty `acl`, the second is `FAILED`. The outcome row is what tells an operator which happened.

The interface this hangs off, deferred with it: `AccessListSource` (`service/connector/acl/`): `AccessList capture(ConnectorConfig, SourceItemRef)` and `Map<SourceItemRef, AccessList> captureForContainer(ConnectorConfig, SourceContainerRef)`. Kept separate from `DocumentConnector` because capture has its own throttling profile, its own failure modes, and its own schedule (D8), and because a source can be readable for content and unreadable for sharing. A connector without a working `AccessListSource` is a connector whose documents are invisible, which needs to be a legible failure rather than a silent one.

What has to happen for this to become active: a principal namespace a source identifier can mint into, which is the identity-side deferral, and the owner's decision about how a customer's directory groups relate to Keycloak's.

### Deferred D8: Effective permissions are read from the source, never inferred from the content feed

The connector asks the source what an item's effective permissions are. It does not derive them from the change feed, and it does not treat an item's absence from the change feed as evidence that its permissions are unchanged.

Sources are inconsistent about this in two specific ways, and both break inference.

They are inconsistent about reporting permission edits at all. A sharing change on an item whose bytes did not change may or may not appear in a delta response, depending on the source, the kind of change, and the API version. A pipeline that reads "not in the delta" as "permissions unchanged" is correct exactly as often as the source happens to be generous, and there is no way to know which case a given customer is in without asking the source directly.

They are inconsistent about inherited changes. Revoking a group's access to a folder changes the effective permissions of every item beneath it, and sources generally report that as one change on the folder rather than as a change on each descendant. A pipeline reading only the item-level feed sees a folder event, has no item to act on, and leaves every document in the tree carrying an access list that stopped being true.

So capture runs on its own trigger, not on the content feed's. Every sync run confirms permissions for the items whose confirmation is due, whether or not those items appeared in the content delta, and records the confirmation time in `permissions_confirmed_through` on the cursor. Content progress and permission progress are two separate things and the run advances them separately.

This is the decision that makes `acl_synced_at` mean what ADR-M004 says it means: when the list was last confirmed against its source, not when it last changed.

### Deferred D9: Folder-level inheritance, so capture is not one call per document

Asking the source for the permissions of every item individually is correct and unusable. A first full enumeration of a large drive is tens of thousands of items, one throttled call each, against a per-tenant throttling budget that already constrains the content sync. The first sync would either take days or spend its whole budget on permission reads and land no documents.

Capture is therefore container-first.

The connector reads permissions for the container, meaning the drive root and each folder in scope, and records the resulting list against that container. An item that inherits its container's permissions, which is the overwhelming majority of items in a normal corpus, takes the container's captured list with no call of its own, and its `connector_item_acl` row records the container it inherited from. A per-item call is made only for an item the source marks as having permissions of its own, which sources do expose: Graph marks an inherited permission entry with `inheritedFrom`, so an item whose permission collection contains an entry without that marker has something unique and is read individually.

This turns a first full enumeration from one call per document into one call per folder plus one call per genuinely uniquely-shared document. On a corpus where sharing is set at team-folder level, which is how companies actually work, that is orders of magnitude fewer calls.

Two consequences follow and both are load-bearing.

A container's permission change invalidates every item that inherited from it. That is the point: one folder read detects a revocation affecting a thousand documents, and the run then performs a thousand payload-only updates, which are cheap, rather than a thousand permission reads, which are not. The container reference on the `connector_item_acl` row is what makes that fan-out a local query.

An item that stops inheriting, meaning somebody set a unique permission on it between runs, has to be detected. A container read alone cannot see it. Detection is the per-item confirmation schedule from D8: an item whose confirmation is due is read individually regardless of what its container said, so an item that quietly acquired unique permissions is corrected within one confirmation interval rather than never.

This is also the decision that made the permission throttling budget separate from the content budget, so that a permission storm could not starve document landing and document landing could not starve permission reads. That split returns with these reads.

### Deferred D10: Deduplication key is content version paired with access-list version

`ManualIngestionService` builds its marker as `manual-ingestion:<key>:<etag>` and skips the object when the marker exists. The ETag hashes content. Unchanged bytes produce an unchanged ETag, produce a marker hit, produce a skip. A permission-only change is by definition an unchanged file, so under a content-only key the most common permission event in any company is structurally invisible.

The key becomes the pair: `manual-ingestion:<key>:<contentVersion>:<aclVersion>`.

`contentVersion` is the ETag exactly as today. `aclVersion` is a stable hash of the sorted principal list, and the sorting is what makes it stable: a source that returns the same permitted set in a different order produces the same hash and is correctly read as no change. Two items sharing a permitted set share a version, which is what makes the container-level comparison in D9 a single equality rather than a set diff.

A permission-only change produces a new key, so the object is processed. A genuine no-op produces a key hit and is still skipped. Nothing about the content path changes.

The hash is taken over a canonical form: principals sorted lexicographically and joined with a separator that cannot occur inside a principal, which the format constraints in `add-auth-and-identity` already guarantee.

Under the current scope the access-list version of a connector-landed document is a constant, one principal derived from the tenant, so pairing it into the key would add a segment that never varies and a second marker format that never earns it. The content-only marker is therefore unchanged in this version, and the pairing returns the moment a captured list can differ between two runs of the same connector.

### Deferred D11: The four-way branch, and the payload-only update path

A run compares two versions for every item it touches, and there are four outcomes, not two.

```mermaid
flowchart TB
    accTitle: The four-way branch a sync takes on content change against access-list change
    accDescr: Only the content-unchanged, access-list-changed path performs a payload-only update, and that path must never re-embed.
    S[Sync sees an item in scope] --> C{content version changed?}

    C -->|no| A1{acl_version changed?}
    C -->|yes| A2{acl_version changed?}

    A1 -->|no| N["No-op<br/>outcome: SKIPPED, reason unchanged"]
    A1 -->|yes| P["Payload-only update<br/>setPayload on existing points<br/>acl, acl_source, acl_version, acl_synced_at<br/>NO re-embed, NO re-chunk<br/>outcome: PERMISSIONS_UPDATED"]

    A2 -->|no| R1["Full re-index<br/>re-parse, re-chunk, re-embed, replace<br/>carry the current acl forward<br/>outcome: UPDATED"]
    A2 -->|yes| R2["Full re-index with the new acl<br/>outcome: UPDATED"]

    style P fill:#2d4a5e,stroke:#8fbcd4,color:#ffffff
```

The path that matters is the one where content is unchanged and the access list is not. Re-embedding a 200-chunk document to change one keyword array is the difference between a revocation taking seconds and a revocation taking an hour, and during that hour the revoked group can still retrieve the document. It also spends an embedding API call per chunk on a change that touched no text.

Spring AI's `VectorStore` abstraction cannot express this. It offers `add` and `delete`, and `add` means embed. The payload-only path therefore uses the native Qdrant client's `setPayload` against the points whose payload already identifies that source, updating exactly the four access-list keys and touching nothing else. The Qdrant client is already a declared dependency in `apps/ascend-agent/build.gradle.kts` as `libs.qdrant.client`, so this is a second and narrower use of a dependency that is already present, not a new one.

The update carries the same tenant predicate every other Qdrant operation carries, so it can never reach across tenants, and it names the four access-list keys explicitly rather than replacing the payload, so it cannot drop `source`, `type`, `title`, or `tenant_id` by omission.

Under the current scope only two of these four branches are reachable, because the access-list version of a connector-landed document never changes, and the two that remain are the ones the existing content-only dedup already implements. The carve-out to the no-direct-vector-store-writes rule is therefore not taken in this version, and `add-connector-framework` D1 states the rule without an exception. The carve-out returns with the branch, and the `payload-only-update-carve-out` record records it as deferred rather than as withdrawn, so a future reader finds a reviewed exception rather than an invitation to invent one.

### Deferred D12: The `PERMISSIONS_UPDATED` outcome, and permission confirmation state on the cursor

The existing per-file actions, `ADDED`, `UPDATED`, `DELETED`, `SKIPPED`, `FAILED`, all describe indexing. A run that touched an item, changed something that matters, and indexed nothing is none of them. Recording it as `UPDATED` claims a re-index that did not happen; recording it as `SKIPPED` claims nothing happened while a revocation was taking effect.

`PERMISSIONS_UPDATED` is added, carrying the `acl_version` that was written. It is not bookkeeping. It is how an operator tells "the sync is working and permissions moved" from "the sync did nothing", and a flat zero on that counter across a customer with active sharing changes is the signal that permission capture has stopped while the content sync still looks healthy.

The cursor gains permission confirmation state for the same reason. A cursor holding only a content delta token records how far the content feed has been consumed and says nothing about whether permissions were ever confirmed, so a connector whose permission reads have failed for a week looks identical to one fully up to date. `permissions_confirmed_through` is the timestamp through which items in this connector's scope have had their permissions confirmed, and it advances only when confirmation actually happened. It is what the staleness sweep in D14 measures and what the access-list-age metric reports.

Neither is minted in this version. No run changes a permission, so the outcome value would never be written, and no run confirms one, so the timestamp would never advance off its initial value. An enum value nothing produces and a timestamp nothing moves are both worse than absent, because a reader takes them as evidence the mechanism exists.

### Deferred D13: An over-long access list is a capture failure, never a truncation

The cap is 64 principals per list, matching ADR-M004 and ADR-M007. An item whose permitted set exceeds it fails capture: outcome `FAILED` with a cap reason, no chunk written with a shortened list, and no chunk for that item retrievable.

Truncating an allow list silently denies people access they actually have. The symptom is a person who cannot find a document they can open in SharePoint, and that symptom is indistinguishable from a bug in retrieval, in embedding, in chunking, or in the model. It costs a debugging session across four subsystems. A capture failure costs a line in a sync history with a file name attached. There is no version of quietly dropping the last few principals that is cheaper to operate than that.

This is also why the cap check runs before the object storage write and before the dedup key is recorded, so a capped item leaves no half-state a later run reads as complete.

A connector-landed list in this version holds exactly one principal, so a cap of 64 cannot be reached by any input the connector can produce. The check is deferred here rather than kept as a guard that cannot fire. The read-side cap that `add-tenant-isolation` enforces on any list it composes is unaffected and stays where it is, which is the right place for a guard that a direct upload's administrator-assigned list can genuinely breach.

### Deferred D14: Staleness sweep, and administrator-triggered immediate resync

Two controls make the staleness window in ADR-M004 operable rather than merely disclosed.

The sweep. A scheduled job scans `connector_item_acl` for rows whose `acl_synced_at` is older than a configured maximum age, and for each one empties the `acl` on that item's chunks through the same payload-only path as D11, recording the outcome. Under deny-by-default an emptied list makes the document invisible immediately.

That is a deliberately blunt control, and the bluntness is the design. If permission capture stops silently, whether by a revoked client secret, a delta token stuck in a resync loop, a scheduler that never fires, or an administrator removing a Graph permission, the alternative to the sweep is a corpus that keeps answering from permissions frozen at the moment capture died, with nothing anywhere indicating a problem. A product that goes quiet is a support ticket on the first day. A product that keeps answering from permissions that stopped being true is an incident discovered by whoever it harmed. The sweep chooses the first.

The maximum age is configured per connector with a platform default, and it has to be comfortably larger than that connector's confirmation interval or a healthy connector sweeps its own documents. The framework rejects a configuration where the maximum age is not at least a stated multiple of the confirmation interval, because that particular misconfiguration is silent right up until it empties a corpus.

The immediate resync. The trigger-sync-now endpoint already exists in this change for content. It gains a permissions-only mode: confirm permissions across the connector's scope now, apply payload-only updates, and do not touch content. When somebody revokes access to a document and needs it to take effect now, they must not have to wait for a cron tick, and they must not pay a full content re-enumeration to get a permission refresh.

The freshness check of `add-connector-framework` D19 is what this becomes in the meantime. The instinct, that a silent outage has to become a visible one and that the control must not depend on the thing that failed, is kept and re-aimed at the sync rather than at the access list. The enforcement half is what is deferred, because there is no stale authorization decision to contain when the only grant on the document is the company itself. The permissions-only trigger mode is deferred with it, since a permissions-only run has nothing to confirm and nothing to write.

### Deferred D15a: The directory grant, and the insufficient-grant detection

Turning a permission entry into a principal is not covered by the content grants. A permission entry names an identity, and mapping that identity onto an `entra:group:<object id>` principal means reading directory group objects. Microsoft's reference for a group's transitive members gives, for application permission type, a least-privileged permission of `GroupMember.ReadBasic.All`, with `Directory.Read.All`, `Group.Read.All`, and `GroupMember.Read.All` among the higher-privileged alternatives. None of `Files.Read.All`, `Sites.Read.All`, or `Sites.ReadWrite.All` grants any of that. An app registration holding only the content grants can read a permission collection and cannot confirm that the group it names exists, is a security group, or carries the object id it appears to carry.

The grant this change documented was therefore `Sites.Read.All` plus `GroupMember.Read.All`, both application permissions, both admin-consented.

The failure this exists to prevent is specific and quiet. Microsoft's own note on listing item permissions says the collection may not be available to every caller and that a non-owner caller receives only the permissions that apply to it. An app registration with an insufficient grant therefore does not necessarily get a clean authorization error. It can get a short list. A capture that accepts a short list writes a narrower access list than the truth and silently denies people, which is D13's failure mode arriving through a different door. Capture therefore treats an unexpectedly empty or unattributable permission collection on an item it can otherwise read as a capture failure, not as an empty list.

Both the grant and the detection return with capture. Until then the onboarding asks a customer for content grants only, which is a smaller consent and one this change can honestly justify.

### Deferred D16: Source identifiers are principals only when one directory backs both the login and the files

The existing scoping design assumes an identifier the source hands back is directly meaningful to the rest of the system. That holds in exactly one case: the customer's login provider and their file store are the same vendor's directory, so the group object id on a SharePoint permission entry is the same object id that appears in the token's group claim. That is Shape 1 in `docs/architecture/permission-aware-retrieval.md`, and it is the common case.

It does not hold otherwise, and a connector that assumes it produces principals nobody holds. A group identifier from a Google Drive permission means nothing to a caller whose principals came from Entra ID, and the resulting access list is syntactically valid, semantically empty, and looks entirely normal in the payload.

So capture states its assumption rather than relying on it. A connector declares the directory namespace it emits principals in. Where that namespace matches the tenant's login directory, the identifiers are used directly. Where it does not, the principals are still captured and still written, and they become meaningful to a caller only through the cross-provider identity link owned by `add-auth-and-identity`, which is what resolves a person's principals across both providers. Nothing here reimplements that join. Capture's job is to emit correctly-namespaced principals and to be honest about which namespace they are in.

A permission entry naming an identity the connector cannot map into a known namespace is a capture failure for that item, per D7. It is not silently dropped, because a dropped entry is a narrowed allow list, which is D13's failure again.

The escape route in the second half of this decision, that an out-of-namespace principal becomes meaningful through the cross-provider identity link, is not available under the current scope: that link is itself deferred on the identity side, so there is nothing to make such a principal mean anything. Under this scope every identifier a source hands back is out of namespace, including the Shape 1 case, because the login directory is Keycloak and no file store's permission entry names a Keycloak group. That is the whole reason capture is deferred rather than shipped in a degraded form.

### Deferred open questions

Three of this change's open questions exist only under capture and are parked with it. Owner decision 65.17 of 2026-10-04 closes all three, so the capture work starts from these answers when it returns: the permission recheck runs every hour by default, anyone-with-the-link and anonymous sharing is hidden by default, and an item shared only with individual people gets an empty list with a distinct capture reason. The paragraphs below keep the reasoning.

The default permission confirmation interval, and therefore the default upper bound on how long a revocation at the source takes to reach retrieval. This is a number stated to a customer rather than picked to look reasonable in a configuration file, and it trades directly against Graph throttling on large tenants. Open question 2 in `docs/architecture/permission-aware-retrieval.md` is the same question. Closed by owner decision 65.17 of 2026-10-04: the default permission confirmation interval is one hour, so a revocation at the source reaches retrieval within about one hour, and it is a per-connector setting.

How anonymous and anyone-with-the-link sharing maps to an access list. Both plausible mappings are wrong for somebody: mapping it to `tenant:everyone:{tenantId}` makes a document the customer shared publicly retrievable by their whole company, and mapping it to nobody makes a genuinely open document invisible. This is open question 3 in `docs/architecture/permission-aware-retrieval.md`. The shape is a per-connector setting with a deliberate default. Closed by owner decision 65.17 of 2026-10-04: the default is hidden, so a link-type or anonymous permission entry adds no principal, and an operator who wants such documents visible to the company turns the per-connector setting on, which maps them to `tenant:everyone:{tenantId}`.

Whether an item granted directly to individual people, with no group entry at all, should fail capture or produce an empty list. ADR-M007 rules out expanding it into the list, and both remaining options are defensible: failing is honest and noisy on a corpus with many personally-shared files, empty is quiet and correct under deny-by-default. Closed by owner decision 65.17 of 2026-10-04: an empty list with a distinct capture reason recorded on the outcome, so the count is visible without every such file failing a run.

## Risks / Trade-offs

- Connector-synced documents are company-visible in this version, so a customer whose SharePoint has genuinely restricted material gets coarser access in AscendAI than they have at the source. This is the Named limitation section above rather than a bullet with a mitigation, it is a product disclosure, and it is stated to a customer in the SharePoint section of `docs/CONNECTORS.md` rather than left for them to discover. The alternative under deny-by-default was not finer access, it was a corpus visible to nobody.
- [Graph throttling on large tenants, initial full sync of a big site can hit 429 storms]: delta paging with `Retry-After` compliance, bounded per-run throttle budget, `PARTIAL` status with resumable cursor. `docs/CONNECTORS.md` records that the first sync of a large site can take multiple runs.
- [Delta token invalidation (Graph returns `410 Gone` or `resyncRequired`)]: the connector resets the content cursor and performs a full re-enumeration, and the registry ETag dedup of `add-connector-framework` makes re-landing unchanged bytes a no-op.
- [Deletion propagation ordering, file deleted and re-added between syncs]: the connector returns delta entries in Graph-returned order per item id, since Graph collapses per-item history in a delta page, so the last state wins.
- [A client secret is revoked in Entra ID and the connector stops syncing silently]: the freshness check of `add-connector-framework` D19 marks the connector stale, and the run history shows the authentication failure class.
- [Secret leakage via logs or API echoes]: the framework's write-only credential fields and reference-only persistence (its D24), and this change's own test asserting no Graph token or client secret appears in logs at any level during a sync, including failure paths.
- [Sibling-change coupling, this change cannot ship before its dependencies]: every dependency lands earlier under the owner build order of 2026-10-04, and `tasks.md` names what each task builds on.
- [A future reader takes the absence of capture code for a decision that per-document permissions do not matter]: the Named limitation section, the Deferred section, and the deferral notes on the `effective-permissions-not-change-feed` record through the `access-list-staleness-sweep` record all say the opposite, in the change and in the records that outlive it.

## Migration Plan

The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep, so this plan has no backfill, no copy step and no rollback script that restores data. This holds only until the first real customer deployment.

1. One Flyway migration admits `SHAREPOINT` in the framework's type check constraint (D3b) and changes nothing else. Flyway runs forward only, and there is no manual rollback script.
2. The SharePoint connector ships dark: no `SHAREPOINT` connector rows exist until an `ADMIN` creates one, so default behaviour is byte-identical to the framework without this change.
3. Connector-landed documents carry the tenant-everyone grant from their first sync, stamped by the ingestion producer default that `add-tenant-isolation` owns. There is no phase in which a connector-landed document exists with no access list in a company deployment, because the stamp happens at ingestion for every document the pipeline sees.
4. Rollback: disable every `SHAREPOINT` connector, which removes their `connector-sync` executions, then revert code. Documents already landed keep the access lists the ingestion producer stamped, which are `add-tenant-isolation`'s to interpret and unaffected by a rollback of this change.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. Its new connector type has no earlier data, so it keeps no backfill and starts from empty stores.

## Owner decisions of 2026-10-07

Answer 75.1: the review of 2026-10-07 is fixed here. Item 49: the access assignment for direct uploads is no longer called an open question, because `PUT /api/v1/documents/{id}/access` of `add-tenant-administration` (its D8) provides it. Item 52: the retrieval scope spec of task 5.5 runs on the scripted model of `close-agent-test-gaps`, so no hosted model is used.

## Owner decisions of 2026-10-08

Answer 76.2 (the owner strongly prefers Mockoon, and no group 3 to 5 change uses the earlier mock server any more), applied to this change's own tests and confirmed by owner answer 78.3 of 2026-10-08 (unit tests use the JDK `HttpServer`, integration and e2e fakes use Mockoon containers): the Graph client tests of tasks 2.2 to 2.7 run against a local JDK `com.sun.net.httpserver.HttpServer` fake, as `close-agent-test-gaps` D1 already uses, so no test dependency is added. The Graph stub of the end-to-end specs (task 5.2) is described by answer 82.5 below, which replaced the separate stub container and environment file this answer first named (owner answer 93, review item C11: that stale description is removed so nobody builds a second container). The global variable `graph_stub_state` and the admin calls stay.

Answer 78.1: the provider `scripted` uses `default-embedding: openai`, and the deterministic phase overlay points the agent's own embedding entry `openai` at Mockoon. There is no separate scripted embedding entry, and every vector file of this change is 1536 long (`ascendai-1536` and `ascend_memory_1536`). Since answer 91.1 no memory of the deterministic phase reaches `ascend_memory_1536`, and the vector files stay 1536 long for `ascendai-1536`.

Answer 78.3: both kinds of fake stay for this change's own tests: unit tests use the JDK `HttpServer`, and integration and e2e fakes use Mockoon containers. This confirms the application recorded in the answer 76.2 entry above.

Answer 78.4: superseded by answer 82.5 below. The Graph stub rules live in `scripted-model.json` and the reply files in `scripted-model/responses/graph-stub/`. No file named `graph-stub.json` exists.

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users, under the tenant-qualified id `{tenantId}:{userId}`, in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 5.5). Superseded by answer 91.1 below.

Answer 81.3, addition (mandatory): every host and port of this change follows the rules of `close-agent-test-gaps` D8, so the plan works on Linux Docker Engine, where `host.docker.internal` does not resolve by itself. Checked on 2026-10-08: the earlier plan started the Graph stub "on a fixed loopback port" and let the agent reach it from its container, which a port published on `127.0.0.1` cannot serve on Linux. The agent reaches the stub by container name on the stack's network through the settings of task 2.8 (rule 1), and Bruno reaches the admin API on a port published on `127.0.0.1` only (rule 2). Answer 82.5 below names the container: the stub is served by `e2e-scripted-model`, with no container of its own.

Answer 82.5 (the owner called the earlier design overengineered and not best practice): one Mockoon container, `e2e-scripted-model` of `close-agent-test-gaps`, serves every HTTP fake of the plans, the Microsoft Graph stub of this change included. The stub has no container of its own and no environment file of its own. Its routes and rules live in the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` under the path prefix `/graph-stub/`, which no other fake uses (`close-agent-test-gaps` D5 lists the prefix of every fake), and its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/graph-stub/`. The e2e overlay points both base addresses of task 2.8 at `http://e2e-scripted-model:3000/graph-stub` (container port 3000, `close-agent-test-gaps` D8 rule 1), so the Graph calls arrive below `/graph-stub/` and the token calls of Entra ID too. The state of the stub is the Mockoon global variable `graph_stub_state`, a name no other fake uses, set with `POST http://127.0.0.1:7033/mockoon-admin/global-vars` and cleared with `POST http://127.0.0.1:7033/mockoon-admin/state/purge` (the scripted model is published as `127.0.0.1:7033`). A request log read keeps only the requests whose path starts with `/graph-stub/`. The specs therefore run in the harness phase of `close-agent-test-gaps` D7, serial with every other spec that uses the harness. The deterministic phase runs exactly two test containers, `e2e-scripted-model` and `e2e-fake-mcp`. Unit tests keep the JDK `HttpServer` (answer 78.3) (tasks 5.1, 5.2 and 5.8).

Answer 86.3: task 2.8 names the two base address settings `app.connector.sharepoint.graph-base-url` and `app.connector.sharepoint.token-base-url`, defaulting to the real Microsoft Graph and Microsoft login addresses. This settles the open point of CANON 24.7. The e2e overlay sets both to `http://e2e-scripted-model:3000/graph-stub` (task 5.2), and a national cloud sets them to its own hosts.

Answer 86.4: the Mockoon route prefix `/graph-stub/` and the state variable `graph_stub_state` stay as answer 82.5 names them.

Answer 86.1: no integration test of this change uses an HTTP fake in a Testcontainers Mockoon container. If one is added, it loads `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`. The Graph client unit tests keep the JDK `HttpServer` (answer 78.3).

Answer 87 (rule R1, several agent instances): checked. Syncs run as executions of the shared scheduler through `add-connector-framework`, so one instance runs a sync. The Graph access token is cached in the memory of the instance that runs the sync, which is correct per instance, because each instance may hold its own valid token. The credential is read from the shared `ConnectorCredentialStore`. Nothing else of this change holds state.

Answer 88 (rule R2): the `SHAREPOINT` type stays a plug-in of the framework, and every company feature of this change stays.

Answer 88.1 (tenant backfill removed): no effect. This change already starts from empty stores (answer 73.1).

Answer 85.1: no plan text of this change exports a secret in a shell. The SharePoint client secret is stored through `ConnectorCredentialStore`, and the e2e credential of the stub is a placeholder test value.

Answer 91.1 (broadcast of `close-agent-test-gaps`): the retrieval scope spec of task 5.5 runs in the deterministic phase, where AscendMemory is the fake under `/ascend-memory/` of the one Mockoon container. Its AscendMemory wipes are removed.

Answer 91.3: the connector CRUD spec (task 5.3) is removed, because the framework's connector API spec and the tests of tasks 1.1 and 2.1 prove it, and the Graph fault part of the freshness spec (task 5.6) is removed, because the Graph client tests of tasks 2.4, 2.5 and 2.7 prove it. The sync and history, retrieval scope and freshness specs stay, because they prove the real landing, the real tenant filter and the real freshness check.

Answer 93: review item C11, the stale description of a separate Graph stub container and environment file in the answer 76.2 and 81.3 entries is removed. Review item C1, the five deferred decision records are not installed on archive and stay in the archived change folder (`decisions/README.md`, Decision Records).

Answer 98 (the configuration rule, CANON 31.11 to 31.13): every value of this change with a default is a setting read from the environment, written as `${ENV:default}` in `application.yaml`, with the same default in the `@ConfigurationProperties` record and the line `- ENV=${ENV:-default}` on the `ascend-agent` service in `compose.yaml`. Settings made external: `app.connector.sharepoint.graph-base-url` (`APP_CONNECTOR_SHAREPOINT_GRAPHBASEURL`) and `app.connector.sharepoint.token-base-url` (`APP_CONNECTOR_SHAREPOINT_TOKENBASEURL`), defaults the real Microsoft Graph and Microsoft login addresses of answer 86.3 (task 2.8), `app.connector.sharepoint.max-file-size` (empty by default, which takes the upload limit `spring.servlet.multipart.max-file-size`, a derived value whose input is the setting), `app.connector.sharepoint.throttle.max-retries`, `app.connector.sharepoint.throttle.backoff-initial`, `app.connector.sharepoint.throttle.backoff-max`, `app.connector.sharepoint.throttle.run-budget`, `app.connector.sharepoint.connect-timeout` and `app.connector.sharepoint.read-timeout` (task 2.9). The defaults of the retries, the two backoff values, the run budget and the two timeouts are not decided and are listed for the owner. Kept as constants, because they are not operational: the connector type `SHAREPOINT`, `source_type` `connector:sharepoint`, the Graph API paths (`/sites/{site-id}/drives`, `/drives/{drive-id}/root/delta`), the access-list values `tenant:everyone:{tenantId}` and `tenant-default`, and the e2e stub prefix `/graph-stub/` and state `graph_stub_state` (test-only). Not this change's values: the allowlist `app.ingestion.upload.allowed-mime-types` and the upload limit, which exist already, and the sync cron, maximum sync age and freshness check of `add-connector-framework`. Test-only values (the stub address `http://e2e-scripted-model:3000/graph-stub`) stay in the deterministic overlay that the deterministic phase copies into the running agent (`close-agent-test-gaps` D7), never in `compose.yaml`. The 64-principal cap of Deferred D13 belongs to deferred capture and follows ADR-M004 and ADR-M007. Rows go to `apps/ascend-agent/docs/CONFIGURATION.md`, each description ending "Added by `add-document-connectors`." (task 4.3). No test or measurement of this change names LM Studio as a default (checked in round 98).

## Open Questions

1. Closed (owner decision 65.8 of 2026-10-04): the Google Drive inline permissions do not hold for the files a company connector reads. The Drive v3 File reference says `permissions[]` is "Not populated for items in shared drives" (https://developers.google.com/workspace/drive/api/reference/rest/v3/files, read on 2026-10-04), so a file in a shared drive needs one `permissions.list` call. The `sharepoint-first-despite-google-being-cheaper` record carries a correction of 2026-10-04: SharePoint stays first for the customer reason alone, and both sources need per-item permission requests.
2. Closed (owner rule of 2026-10-04): the framework, its run history, its freshness check, its API and its credential store moved to `add-connector-framework`. This change keeps SharePoint, its access list rules and the deferred capture design, and depends on that change.
3. Closed (owner answer 82.5 of 2026-10-08): the Graph stub has no container of its own. It is served by `e2e-scripted-model` under the path prefix `/graph-stub/`, reached by containers at `http://e2e-scripted-model:3000/graph-stub` and by Bruno at `http://127.0.0.1:7033` (task 5.2).

Three further open questions belong to capture and are parked in the Deferred section rather than left here, since none of them can arise in this version.

## Decision Records

Decisions this change makes that go beyond the monorepo records ADR-M004 through ADR-M009 are written up under `decisions/`. These drafts carry no number yet (`ADR-NNN-<slug>.md`) and each takes the next free number in `apps/ascend-agent/docs/architecture/decisions/` at implementation time. See `decisions/README.md` for the index, for which records are deferred under the current scope, and for where those files land when the change is archived: only the record that is not deferred is installed into `apps/ascend-agent/docs/architecture/decisions/`, and the five deferred records stay in the archived change folder (owner answer 93, review item C1). The `sync-freshness-check-replaces-the-sweep` record moved to `add-connector-framework` with the freshness check on 2026-10-04.
