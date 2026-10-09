## Purpose

Makes the Markdown ingestion path index YAML front matter as plain properties and Obsidian wiki links as readable text, for every Markdown document whatever its source.

## ADDED Requirements

### Requirement: Front matter is read as properties, not indexed as YAML

When a Markdown document starts with a YAML front matter block, the Markdown path SHALL remove the block from the body and SHALL index its scalar properties and its lists of scalars as one leading block of `name: value` lines, joining list items with commas. Nested values SHALL be left out. A front matter block that is not valid YAML SHALL be indexed as ordinary text and logged at WARN without its content.

#### Scenario: Properties become plain lines

- **WHEN** a note starts with front matter holding `tags: [home, money]` and `status: draft`
- **THEN** the indexed text begins with the lines `tags: home, money` and `status: draft`
- **AND** the indexed text holds no `---` line of the front matter

#### Scenario: Invalid front matter is kept as text

- **WHEN** the front matter block is not valid YAML
- **THEN** the document is indexed with the block as ordinary text
- **AND** one WARN line names the document

### Requirement: Title comes from front matter first

The title of a Markdown document SHALL be its front matter `title` property when present, else its first heading, else its file name without the extension. A property line SHALL never be taken as the title.

#### Scenario: Front matter title wins

- **WHEN** a note has front matter `title: Budget 2027` and a first heading `Notes`
- **THEN** its chunks carry the title `Budget 2027`

#### Scenario: Front matter without title does not become the title

- **WHEN** a note has front matter `status: draft` and no heading, and is named `Plan.md`
- **THEN** its chunks carry the title `Plan`

### Requirement: Wiki links are rendered as readable text

The Markdown path SHALL render Obsidian wiki links as text: `[[Note]]` as `Note`, `[[Note|alias]]` as `alias`, `[[Note#Heading]]` as `Note > Heading`, `[[#Heading]]` as `Heading`, and `[[Note#^block]]` as `Note`. An embed of a note `![[Note]]` SHALL be rendered as `Note`, and an embed of any other file such as `![[image.png]]` SHALL be removed. Obsidian comments `%% ... %%` SHALL be removed, and a callout marker `[!type]` at the start of a block quote SHALL be removed with its text kept. A Markdown document with none of these constructs SHALL be indexed exactly as before this change.

#### Scenario: Links and aliases

- **WHEN** a note says `Call [[People/Anna|Anna]] about [[Budget#Q4]]`
- **THEN** the indexed text says `Call Anna about Budget > Q4`

#### Scenario: Image embed and comment removed

- **WHEN** a note holds `![[scan.png]]` and `%% private remark %%`
- **THEN** neither the embed nor the remark appears in the indexed text

#### Scenario: Plain Markdown unchanged

- **WHEN** a Markdown document without front matter, wiki links, comments or callouts is ingested
- **THEN** its indexed text and title are identical to what the path produced before this change
