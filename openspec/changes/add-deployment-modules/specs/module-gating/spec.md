## Purpose

Defines what a switched-off module means inside ascend-ai-agent: nothing of it exists, the core works without it, and a tenant can be given fewer switchable modules than the deployment runs.

## ADDED Requirements

### Requirement: A switched-off module leaves nothing behind in the agent

When a switchable module is not active, the agent SHALL create no bean of that module, SHALL offer no tool of it to the model in any chat turn or background run, SHALL register no HTTP route of it, SHALL make no connection attempt to its services or MCP servers, SHALL register no meter of it, and SHALL list none of its endpoints in the OpenAPI document. A request to a route of a module that is not active SHALL get the same 404 problem detail as any unknown path. A bean that needs several modules SHALL exist only when all of them are active.

#### Scenario: Weather off

- **WHEN** the agent runs with `ASCEND_MODULES=ocr`
- **THEN** no `weather_` tool is offered and no connection to `ascend-weather-mcp` is attempted

#### Scenario: OCR off

- **WHEN** the agent runs with `ASCEND_MODULES` empty
- **THEN** no `AscendOcrClient` bean exists and no request is sent to ascend-ocr

#### Scenario: Bean that needs two modules

- **WHEN** a bean is marked for `web-search` and `web-download` and only `web-search` is active
- **THEN** the bean is not created

### Requirement: The core works with no switchable module

A chat turn on `POST /api/v1/ai/prompt`, document upload and search, semantic memory, and the sandbox tools SHALL work with only the core active. Code of the core SHALL NOT refer to a class of a switchable module. When the core needs something a switchable module provides, it SHALL declare a port that the module implements, and an inactive module SHALL leave that port without an implementation. Retrieved documents and semantic memories SHALL reach the chat through context contributor ports, and the core SHALL contribute them in every deployment.

#### Scenario: Core preset chat turn

- **WHEN** the agent runs with the `core` preset, a document has been ingested, and a prompt about it is sent
- **THEN** the response is 200 with an answer
- **AND** the prompt sent to the model holds the retrieved document context
- **AND** the response lists the document among its sources

#### Scenario: Core preset upload

- **WHEN** the agent runs with the `core` preset and a PDF whose every page has a text layer is uploaded for ingestion
- **THEN** the PDF is ingested and becomes searchable

### Requirement: Every module bean is marked and the marking is checked

Every controller, agent tool, scheduled task and outbound client SHALL either be marked with the switchable module or modules it belongs to, or be on the explicit list of core classes. Every name in a marking SHALL be a switchable module of the catalog, never `core-chat` or a core name. A test SHALL fail when such a class is neither marked nor on the core list, or when a marking names an unknown module or a core name.

#### Scenario: Unmarked controller

- **WHEN** a new controller outside the core list is added without a module marking
- **THEN** the marking coverage test fails naming the class

#### Scenario: Core class marked by mistake

- **WHEN** a class is marked with `@ConditionalOnModule("rag")`
- **THEN** the context fails to start naming the class and the core name `rag`

### Requirement: Each MCP connection belongs to a module

An MCP connection MAY name the switchable module it belongs to. A connection that names no module, such as `e2e-fake` of the deterministic test harness, SHALL belong to no switchable module and SHALL always be connected, in every Spring profile (owner answer 90 of 2026-10-08). A connection that names a module outside the catalog SHALL stop the start. No profile SHALL change these rules. `ascend-weather-mcp` SHALL belong to `weather`, `ascend-web-hunter` to `web-search` and `ascend-audio-scribe` to `audio`. Only a connection of an active module SHALL get a connection: a connection of an inactive module SHALL never be initialized, SHALL never be retried, and SHALL have no line in the readiness banner (capability `mcp-startup-resilience`).

#### Scenario: Connection of an inactive module

- **WHEN** the agent starts with `ASCEND_MODULES=ocr`
- **THEN** no request is sent to the URL of the `ascend-web-hunter` connection
- **AND** the `MCP servers:` section of the readiness banner has no line for it

#### Scenario: A connection with no module is always on

- **WHEN** the agent starts with `ASCEND_MODULES` empty, the shipped profile `SPRING_PROFILES_ACTIVE=docker`, and a connection `e2e-fake` that names no module, configured by the test settings that the deterministic phase copies into the running agent
- **THEN** the agent starts and connects `e2e-fake`
- **AND** no check of the start depends on a test profile, because no `e2e` profile exists

### Requirement: Images and scanned pages are refused when ocr is off

When `ocr` is not active, the agent SHALL do no OCR reading at all. An image file, or a PDF with at least one page without a text layer, SHALL be refused as a whole with HTTP 422 and an RFC 7807 problem detail with the code `module_required`, whose detail names the file and the module `ocr`, and whose detail for a PDF names the pages without a text layer. Nothing of a refused document SHALL be stored, and the agent SHALL NOT send it, or any page of it, to Docling, to Docling's OCR engine, or to ascend-ocr. When `ocr` is active, the agent SHALL keep sending images and pages without a text layer to ascend-ocr.

#### Scenario: Image upload without ocr

- **WHEN** the agent runs with `ASCEND_MODULES` empty and a PNG file is uploaded for ingestion
- **THEN** the response is 422 with `Content-Type: application/problem+json` and `code` `module_required`
- **AND** the detail names the file and the module `ocr`
- **AND** no request is sent to Docling or to ascend-ocr, and no chunk of the file is stored

#### Scenario: Scanned PDF upload without ocr

- **WHEN** the agent runs with `ASCEND_MODULES` empty and a PDF whose page 2 has no text layer is uploaded for ingestion
- **THEN** the response is 422 with `code` `module_required` and a detail that names page 2 and the module `ocr`
- **AND** no page of the PDF is sent to Docling and no chunk of it is stored

#### Scenario: Scanned PDF upload with ocr

- **WHEN** the agent runs with the `company-docs` preset and a PDF whose page 2 has no text layer is uploaded
- **THEN** page 2 is read by ascend-ocr and the PDF is ingested

### Requirement: A tenant can be granted fewer switchable modules than are active

The effective modules of a request SHALL be the active modules narrowed by the module access rule of the caller's tenant, where the tenant SHALL be the one `TenantContext.currentTenantId()` answers. The module access rule SHALL be a replaceable port whose default grants every active module to every tenant, and a registered implementation SHALL replace the default with no edit of this capability's code. A switchable module the tenant is not granted SHALL contribute no tool to that tenant's chat turns and runs, and its routes SHALL answer that tenant with HTTP 403 and an RFC 7807 problem detail with the code `module_denied` that names the module. A tenant grant SHALL NOT widen beyond the active modules, and a grant SHALL include every module that each granted module requires. The core SHALL be effective for every tenant and SHALL NOT be narrowed by a module grant.

#### Scenario: Default grant

- **WHEN** no tenant policy exists and the agent runs with `ASCEND_MODULES=ocr,weather`
- **THEN** every tenant's effective modules are `core-chat`, `ocr` and `weather`

#### Scenario: Tenant without weather

- **WHEN** a registered module access implementation grants tenant `default` no `weather` and a user of `default` sends a prompt
- **THEN** no `weather_` tool is offered to the model for that turn

#### Scenario: Core routes are never denied

- **WHEN** a registered module access implementation grants tenant `default` no switchable module and a user of `default` calls `POST /api/v1/ingestion/upload`
- **THEN** the request is not refused with `module_denied`

### Requirement: The agent tells callers which modules they have

`GET /api/v1/modules` SHALL return the caller's effective modules, `core-chat` first, each with its name, title and description, plus the name of the preset when the active list equals one. It SHALL need the same authentication as every other user endpoint and SHALL belong to the core.

#### Scenario: Company deployment

- **WHEN** the agent runs with `ASCEND_MODULES=ocr` and an authenticated user calls `GET /api/v1/modules`
- **THEN** the response is 200 and lists exactly `core-chat` and `ocr` with the preset `company-docs`

### Requirement: Active modules are visible at startup

The startup readiness banner SHALL hold a `Modules:` block that lists `core-chat` and the active switchable modules in name order and the matching preset, if any. The banner and `GET /api/v1/modules` SHALL be the places that show the active modules, and the agent SHALL publish no metric that repeats them.

#### Scenario: Banner

- **WHEN** the agent starts with `ASCEND_MODULES=ocr`
- **THEN** the banner lists `core-chat` and `ocr` with the preset `company-docs`
- **AND** `/actuator/prometheus` holds no `module_active` series
