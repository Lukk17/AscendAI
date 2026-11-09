import json
import re
from typing import Any

import pytest
from pydantic import ValidationError

from src.config.config import settings
from src.crawl.models import (
    DEFAULT_TENANT,
    TENANT_PATTERN,
    CrawlJobList,
    CrawlJobView,
    CrawlRequest,
    CrawlSubmission,
    InvalidTenantError,
    JobCounts,
    JobNotFoundError,
    JobRecord,
    match_glob,
)
from src.session.profile import MAX_URL_LENGTH, InvalidProfileError


def _seeds(count: int) -> list[Any]:
    return [f"https://example{i}.com/" for i in range(count)]


def _req(seeds: list[Any], **kwargs: Any) -> CrawlRequest:
    return CrawlRequest(seeds=seeds, **kwargs)


@pytest.mark.parametrize("profile", ["a\nb", "a" * 65], ids=["newline", "too-long"])
def test_request_refuses_a_bad_profile_as_invalid_profile(profile: str) -> None:
    # when
    with pytest.raises(InvalidProfileError):
        _req(seeds=["https://example.com/"], profile=profile)


def test_request_refuses_a_too_long_seed() -> None:
    # given
    seed = "https://example.com/" + "a" * MAX_URL_LENGTH

    # when
    with pytest.raises(ValidationError) as exc:
        _req(seeds=[seed])

    # then
    assert exc.value.errors(include_input=False)[0]["loc"] == ("seeds", 0)


def test_request_refuses_a_seed_that_normalizes_past_the_limit() -> None:
    # given
    seed = "https://example.com/" + "é" * (MAX_URL_LENGTH // 2)

    # when
    with pytest.raises(ValidationError):
        _req(seeds=[seed])


def test_request_keeps_a_seed_at_the_limit_readable_after_storage() -> None:
    # given
    url = "https://example.com/"
    seed = url + "a" * (MAX_URL_LENGTH - len(url))

    # when
    stored = _req(seeds=[seed]).model_dump_json()

    # then
    assert [str(item) for item in CrawlRequest.model_validate_json(stored).seeds] == [seed]


def test_request_reads_an_empty_profile_as_the_default_profile() -> None:
    # when
    request = _req(seeds=["https://example.com/"], profile="")

    # then
    assert request.profile is None


def test_request_keeps_a_good_profile() -> None:
    # when
    request = _req(seeds=["https://example.com/"], profile="work_1-a")

    # then
    assert request.profile == "work_1-a"


def test_request_defaults_come_from_settings() -> None:
    # when
    request = _req(seeds=["https://example.com/"])

    # then
    assert request.max_depth == settings.CRAWL_DEFAULT_DEPTH == 2
    assert request.page_budget == settings.CRAWL_DEFAULT_PAGE_BUDGET == 100
    assert request.same_domain_only is True
    assert request.respect_robots is False
    assert request.output_format == "text"
    assert request.include_patterns == []
    assert request.exclude_patterns == []
    assert request.extraction_schema is None
    assert request.profile is None


def test_request_rejects_empty_seeds() -> None:
    # when / then
    with pytest.raises(ValidationError):
        _req(seeds=[])


def test_request_accepts_max_seeds_and_rejects_one_more() -> None:
    # when
    request = _req(seeds=_seeds(settings.CRAWL_MAX_SEEDS))

    # then
    assert len(request.seeds) == 20

    # when / then
    with pytest.raises(ValidationError):
        _req(seeds=_seeds(settings.CRAWL_MAX_SEEDS + 1))


def test_request_accepts_non_http_seed_for_guard_refusal() -> None:
    # The D4 SSRF guard refuses non-http seeds at submission with unsafe_uri,
    # so the model keeps the absolute-URL shape and does not pre-reject them.
    request = _req(seeds=["file:///etc/passwd"])

    assert [str(seed) for seed in request.seeds] == ["file:///etc/passwd"]


@pytest.mark.parametrize("field", ["include_patterns", "exclude_patterns"])
def test_request_accepts_max_patterns_and_rejects_one_more(field: str) -> None:
    # when
    request = _req(
        seeds=["https://example.com/"],
        **{field: [f"/p{i}/*" for i in range(settings.CRAWL_MAX_PATTERNS)]},
    )

    # then
    assert len(getattr(request, field)) == 50

    # when / then
    with pytest.raises(ValidationError):
        _req(
            seeds=["https://example.com/"],
            **{field: [f"/p{i}/*" for i in range(settings.CRAWL_MAX_PATTERNS + 1)]},
        )


@pytest.mark.parametrize("depth", [0, settings.CRAWL_MAX_DEPTH])
def test_request_accepts_depth_edge(depth: int) -> None:
    # when
    request = _req(seeds=["https://example.com/"], max_depth=depth)

    # then
    assert request.max_depth == depth


@pytest.mark.parametrize("depth", [-1, settings.CRAWL_MAX_DEPTH + 1])
def test_request_rejects_depth_outside_bounds(depth: int) -> None:
    # when / then
    with pytest.raises(ValidationError):
        _req(seeds=["https://example.com/"], max_depth=depth)


@pytest.mark.parametrize("budget", [1, settings.CRAWL_MAX_PAGES])
def test_request_accepts_page_budget_edge(budget: int) -> None:
    # when
    request = _req(seeds=["https://example.com/"], page_budget=budget)

    # then
    assert request.page_budget == budget


@pytest.mark.parametrize("budget", [0, settings.CRAWL_MAX_PAGES + 1])
def test_request_rejects_page_budget_outside_bounds(budget: int) -> None:
    # when / then
    with pytest.raises(ValidationError):
        _req(seeds=["https://example.com/"], page_budget=budget)


@pytest.mark.parametrize(
    ("setting", "kwargs"),
    [
        ("CRAWL_MAX_SEEDS", {"seeds": _seeds(3)}),
        ("CRAWL_MAX_PATTERNS", {"include_patterns": ["/a/*", "/b/*"]}),
        ("CRAWL_MAX_PATTERNS", {"exclude_patterns": ["/a/*", "/b/*"]}),
        ("CRAWL_MAX_DEPTH", {"max_depth": 2}),
        ("CRAWL_MAX_PAGES", {"page_budget": 11}),
    ],
)
def test_changed_setting_changes_bound(monkeypatch: Any, setting: str, kwargs: dict[str, Any]) -> None:
    # given a tightened setting below the import-time Field bound
    tightened = {"CRAWL_MAX_SEEDS": 2, "CRAWL_MAX_PATTERNS": 1, "CRAWL_MAX_DEPTH": 1, "CRAWL_MAX_PAGES": 10}
    base: dict[str, Any] = {"seeds": ["https://example.com/"]}
    monkeypatch.setattr(settings, setting, tightened[setting])

    # when / then
    with pytest.raises(ValidationError, match="above the current limit"):
        _req(**{**base, **kwargs})


def test_glob_treats_regex_syntax_as_literal() -> None:
    # ".*" as a regular expression matches everything; as a glob it only
    # matches paths starting with a literal dot.
    assert match_glob([".*"], "/guide/intro") is False
    assert match_glob(["/guide/*"], "/guide/intro") is True
    assert match_glob(["/guide/*"], "/other") is False
    assert match_glob(["/exact"], "/exact") is True
    assert match_glob([], "/guide/intro") is False


def test_job_record_defaults() -> None:
    # when
    record = JobRecord(
        job_id="job1",
        tenant_id="acme",
        request=_req(seeds=["https://example.com/"]),
    )

    # then
    assert record.state == "waiting"
    assert record.counts == JobCounts()
    assert record.pages_ndjson_key is None
    assert record.error is None
    assert record.created_at <= record.updated_at


def test_job_record_rejects_tenant_outside_format() -> None:
    # when / then
    with pytest.raises(ValidationError):
        JobRecord(
            job_id="job1",
            tenant_id="../acme",
            request=_req(seeds=["https://example.com/"]),
        )


def test_job_record_json_round_trip() -> None:
    # given
    record = JobRecord(
        job_id="job1",
        tenant_id="acme",
        request=_req(seeds=["https://example.com/"]),
    )

    # when
    restored = JobRecord.model_validate(record.model_dump(mode="json"))

    # then
    assert restored == record


def test_tenant_constants() -> None:
    # then
    assert DEFAULT_TENANT == "default"
    assert re.fullmatch(TENANT_PATTERN, "acme")
    assert re.fullmatch(TENANT_PATTERN, "default")
    assert re.fullmatch(TENANT_PATTERN, "a" * 64)
    assert not re.fullmatch(TENANT_PATTERN, "")
    assert not re.fullmatch(TENANT_PATTERN, "../acme")
    assert not re.fullmatch(TENANT_PATTERN, "Acme")
    assert not re.fullmatch(TENANT_PATTERN, "a" * 65)


def test_job_not_found_error_carries_job_id() -> None:
    # when
    exc = JobNotFoundError("job1")

    # then
    assert exc.job_id == "job1"
    assert "job1" in str(exc)


def test_invalid_tenant_error_carries_tenant() -> None:
    # when
    exc = InvalidTenantError("../acme")

    # then
    assert exc.tenant == "../acme"
    assert isinstance(exc, ValueError)
    assert "../acme" in str(exc)


def test_submission_view_carries_poll_hint() -> None:
    # when
    view = CrawlSubmission(job_id="job1", state="waiting", poll_after_seconds=5)

    # then
    assert view.job_id == "job1"
    assert view.state == "waiting"
    assert view.poll_after_seconds == 5


def test_job_view_from_record() -> None:
    # given
    record = JobRecord(
        job_id="job1",
        tenant_id="acme",
        request=_req(seeds=["https://example.com/"]),
    )

    # when
    view = CrawlJobView.from_record(record)

    # then
    assert view.job_id == "job1"
    assert view.tenant_id == "acme"
    assert view.state == "waiting"
    assert view.counts == JobCounts()
    assert view.pages_ndjson_key is None
    assert view.error is None
    assert view.created_at == record.created_at
    assert view.updated_at == record.updated_at


def test_job_list_view() -> None:
    # given
    record = JobRecord(
        job_id="job1",
        tenant_id="acme",
        request=_req(seeds=["https://example.com/"]),
    )

    # when
    listing = CrawlJobList(jobs=[CrawlJobView.from_record(record)])

    # then
    assert [job.job_id for job in listing.jobs] == ["job1"]


def test_claim_expiries_list_coerced_to_empty_map() -> None:
    # given a record JSON round-tripped through the Lua scripts, whose
    # JSON layer reads an empty map back as an empty array
    record = JobRecord(
        job_id="job1",
        tenant_id="acme",
        request=_req(seeds=["https://example.com/"]),
        claim_expiries=["x"],  # type: ignore[arg-type]
    )

    # then the artifact is coerced back to the map shape
    assert record.claim_expiries == {}


@pytest.mark.parametrize("field", ["include_patterns", "exclude_patterns"])
def test_empty_map_pattern_coerced_to_empty_list(field: str) -> None:
    # given a request JSON round-tripped through the Lua scripts, whose
    # cjson layer writes an empty array back as an empty map
    payload: dict[str, Any] = {"seeds": ["https://example.com/"], field: {}}

    # when
    request = CrawlRequest(**payload)

    # then the artifact is coerced back to the list shape
    assert getattr(request, field) == []


@pytest.mark.parametrize("field", ["include_patterns", "exclude_patterns"])
def test_non_empty_map_pattern_still_rejected(field: str) -> None:
    # given a map with entries, which is genuine bad input and not the artifact
    payload: dict[str, Any] = {"seeds": ["https://example.com/"], field: {"a": "/x/*"}}

    # when / then
    with pytest.raises(ValidationError):
        CrawlRequest(**payload)


def test_job_record_heals_lua_empty_map_patterns() -> None:
    # given a stored record as real Redis leaves it after a script round-trip
    record = JobRecord(
        job_id="job1",
        tenant_id="acme",
        request=_req(seeds=["https://example.com/"]),
    )
    payload: dict[str, Any] = json.loads(record.model_dump_json())
    payload["request"]["include_patterns"] = {}
    payload["request"]["exclude_patterns"] = {}

    # when the status poll reads it back
    restored = JobRecord.model_validate_json(json.dumps(payload))

    # then it validates instead of answering 404
    assert restored.request.include_patterns == []
    assert restored.request.exclude_patterns == []
