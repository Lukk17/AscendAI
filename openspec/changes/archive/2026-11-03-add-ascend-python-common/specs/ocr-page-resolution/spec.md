# Spec Delta

## MODIFIED Requirements

### Requirement: A language the service does not read is refused at submission

The service SHALL refuse a submission whose language is outside `SUPPORTED_LANGUAGES` on both surfaces before anything
is fetched, stored or queued, and SHALL issue no job identifier for it. The refusal SHALL carry the code
`UNSUPPORTED_LANGUAGE`, SHALL answer HTTP 400 on the REST surface with the problem body of `python-service-platform`,
and SHALL name every supported language without echoing the language the caller sent. `ru` and `korean` SHALL NOT be
supported languages by default.

#### Scenario: A Korean submission over REST

- **WHEN** `POST /v1/ocr/jobs` carries `lang=korean` at the shipped defaults
- **THEN** the answer is HTTP 400 with `Content-Type: application/problem+json`, `type` `https://ascend.ai/errors/unsupported-language`, `title` `Bad Request`, `status` 400, `code` `UNSUPPORTED_LANGUAGE`, `detail` `Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan`, `instance` `/v1/ocr/jobs` and a `traceId`
- **AND** it carries no `job_id` and no `Location` header
- **AND** nothing is queued

#### Scenario: A Russian submission over MCP

- **WHEN** `ocr_submit` is called with `lang=ru` at the shipped defaults
- **THEN** the tool fails with `UNSUPPORTED_LANGUAGE: Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan`
- **AND** the URI is never fetched
- **AND** nothing is queued

#### Scenario: An operator's own allowlist

- **WHEN** `SUPPORTED_LANGUAGES` is configured to another list
- **THEN** a language on it is accepted
- **AND** the refusal of any other language names that list
