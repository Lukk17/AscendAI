# ocr-model-selection Specification

## Purpose
Fixes which detection and recognition models the service runs, how a caller's language resolves to a pair of them,
and what the engine cache is keyed by, so the models in use are a decision this repository records rather than a
default the library happened to pick.

## Requirements

### Requirement: The service names the models it runs

The service SHALL construct its OCR engine by naming a detection model and a recognition model explicitly. It SHALL
NOT delegate the choice to the library's own language-to-model resolution. The models a running configuration uses
SHALL be readable from this repository without reading the library's source.

#### Scenario: An engine is constructed

- **WHEN** the service constructs an OCR engine for any supported language
- **THEN** the construction names both a detection model and a recognition model
- **AND** it does not pass a language to the library's own resolution

#### Scenario: A language outside the allowlist

- **WHEN** a request names a language that is not in the supported-language allowlist
- **THEN** the request is refused before any model name is resolved and before any engine is constructed

### Requirement: The default model pair is configuration, and ships as the small member of the current family

The detection and recognition models used by every language the default pair can read SHALL each be settable from
the environment. The shipped defaults SHALL be the small member of PaddleOCR's current model family, which is better
than the previously selected models on both published accuracy axes and materially faster. Changing the deployed
pair, including to a larger member of the same family, SHALL NOT require a code change.

#### Scenario: Shipped default

- **WHEN** the service starts with no model settings supplied
- **THEN** it uses the small member of the current family for both detection and recognition

#### Scenario: An operator selects a different member

- **WHEN** an operator sets the detection and recognition model settings to another member of the family
- **THEN** the service constructs its engines from the named models
- **AND** no code change is required

#### Scenario: A named model the library does not know

- **WHEN** a model setting names a model the library cannot resolve
- **THEN** engine construction fails and the service reports itself not ready, rather than silently substituting
  another model

### Requirement: A language the default pair cannot read resolves to a pair named for it

Where a supported language falls outside the coverage of the default pair, the service SHALL resolve it to a
detection and recognition pair named explicitly for that language. That mapping SHALL be part of the service, not
left to the library's own resolution, and SHALL preserve the models such a language runs today.

#### Scenario: A language outside the default family

- **WHEN** a request names a supported language the default recognition model has no character coverage for
- **THEN** the service constructs the engine from the pair named for that language
- **AND** the recognition model is one that covers that language's script

#### Scenario: A language inside the default family

- **WHEN** a request names a supported language the default pair covers
- **THEN** the service constructs the engine from the configured default pair

### Requirement: Engines are cached by the models they load, not by the language that asked for them

The engine cache SHALL be keyed by the resolved pair of model names. Two languages that resolve to the same pair
SHALL share one cached engine, and the second of them SHALL construct nothing. The cache SHALL remain
least-recently-used and SHALL remain bounded by its configured maximum, which counts cached engines.

#### Scenario: Two languages that resolve to the same pair

- **WHEN** an engine has been constructed for one language
- **AND** a request arrives for a different language that resolves to the same model pair
- **THEN** the cached engine is reused
- **AND** no second engine is constructed

#### Scenario: Two languages that resolve to different pairs

- **WHEN** requests arrive for two languages that resolve to different model pairs
- **THEN** each pair gets its own cached engine

#### Scenario: The cache is full

- **WHEN** a new pair is resolved and the cache already holds its maximum number of engines
- **THEN** the least recently used engine is evicted
- **AND** the eviction is logged and counted, identified by the model pair evicted rather than by a language

#### Scenario: The detector input bound changes

- **WHEN** the configured detector input bound differs between two calls in one process
- **THEN** the cache key does not change with it, because every engine in a process shares one such bound

### Requirement: The image ships the models the configuration names

The container image SHALL pre-cache the model pair its own configuration names as the default, so a first request in
a fresh container loads from disk rather than downloading. The pre-cache step SHALL derive the models from the same
settings the running service reads, so the baked models cannot drift from the deployed default.

#### Scenario: A first request after a fresh start

- **WHEN** a container built from this image serves its first request in a language the default pair covers
- **THEN** no model download occurs

#### Scenario: The default pair is changed and the image rebuilt

- **WHEN** the default model settings are changed and the image is rebuilt
- **THEN** the image bakes the newly named pair, with no second edit anywhere in the build

#### Scenario: A language outside the default pair

- **WHEN** a container serves its first request in a language that resolves to a pair the image did not bake
- **THEN** that pair is downloaded on first use, as any model absent from the image cache is today
