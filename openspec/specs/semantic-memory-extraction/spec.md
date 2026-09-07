# semantic-memory-extraction Specification

## Purpose

Facts are extracted from a conversation turn by asking an LLM for a JSON array, and thinking models routinely wrap that array in reasoning. The extractor recovers the array from a response carrying a preamble, markdown fences, or trailing prose, returns an empty list and a single warning when there is no array at all rather than throwing, and the extraction prompt itself forbids prose so the wrapped response stays the exception rather than the norm.

## Requirements
### Requirement: Robust JSON array extraction from LLM response

The semantic memory extractor SHALL parse the LLM response into a list of fact strings even when the underlying model is a "thinking" model that prepends or surrounds the JSON array with chain-of-thought reasoning, markdown fences, or trailing prose.

#### Scenario: Pure JSON array response

- **WHEN** the LLM returns exactly `["User's name is Luke", "User is a software engineer"]`
- **THEN** the extractor returns a list of those two fact strings

#### Scenario: Thinking-model preamble followed by JSON array

- **WHEN** the LLM returns reasoning text such as `We have two facts: ...\n\n["User's name is Luke", "User is a software engineer"]`
- **THEN** the extractor scans for the last balanced `[ ... ]` substring and returns the two parsed facts

#### Scenario: Thinking-model output with no JSON array at all

- **WHEN** the LLM returns only reasoning prose with no `[ ... ]` block (verbatim from the bug log: `Thus we have two facts: "User's name is Luke" and "User is a software engineer"...`)
- **THEN** the extractor returns an empty list, logs a single WARN with the full raw response, and increments a `memory.extraction.parse_failed` counter — but does NOT throw

#### Scenario: Markdown-fenced JSON array

- **WHEN** the LLM returns ```` ```json\n["User's name is Luke"]\n``` ````
- **THEN** the extractor strips the fence and returns the parsed fact

#### Scenario: Empty array response

- **WHEN** the LLM returns `[]` (with or without surrounding prose)
- **THEN** the extractor returns an empty list and does NOT log a parse-failure warning

### Requirement: Extraction prompt forbids prose

The prompt template used to ask the LLM to extract semantic facts SHALL explicitly instruct the model to output ONLY a JSON array of strings, with no prose, no markdown fences, and no chain-of-thought, and to output `[]` when there are no facts.

#### Scenario: Prompt template inspection

- **WHEN** the extraction prompt template is loaded at startup
- **THEN** it contains an instruction equivalent to "Output ONLY a JSON array of strings. No prose, no markdown fences, no explanation. If no facts, output []."

