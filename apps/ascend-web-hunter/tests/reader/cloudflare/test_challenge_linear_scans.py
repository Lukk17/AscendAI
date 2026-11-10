"""The style body and password input scans read site markup in one pass and match the old patterns."""

import random
import re
import time

import pytest

from src.reader.cloudflare.challenge_detector import ChallengeDetector, has_password_input
from src.reader.cloudflare.challenge_signals import _without_style_bodies, assess

_PAGE_BYTES = 500 * 1024

_SCAN_BUDGET_SECONDS = 1.0

_ORACLE_SEED = 20261108

_ORACLE_CASES = 3000

_ORACLE_MAX_PIECES = 12

_REFERENCE_STYLE_BODY = re.compile(r"(<style\b[^>]*>).*?(</style\s*>)", re.IGNORECASE | re.DOTALL)

_REFERENCE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

_REFERENCE_PASSWORD_INPUT = re.compile(r"<input\b[^>]*\btype\s*=\s*[\"']?password\b", re.IGNORECASE)

_PIECES = (
    "<style>",
    "<STYLE media='x'>",
    "<style",
    "<styles>",
    "</style>",
    "</STYLE  >",
    "</style",
    "<title>",
    "<TITLE lang=en>",
    "<title",
    "<titlebar>",
    "</title>",
    "</TITLE>",
    "</title",
    "sign in",
    "<input ",
    "<INPUT",
    "<inputs ",
    "type=password",
    "TYPE = 'Password'",
    'type="password1"',
    "type=passwords",
    "xtype=password",
    ">",
    "<",
    " ",
    "\n",
    "body{}",
    "a",
)


def _random_markup(rng: random.Random) -> str:
    return "".join(rng.choice(_PIECES) for _ in range(rng.randint(0, _ORACLE_MAX_PIECES)))


def _oracle_markups() -> list[str]:
    rng = random.Random(_ORACLE_SEED)

    return [_random_markup(rng) for _ in range(_ORACLE_CASES)]


def test_style_bodies_are_emptied_exactly_like_the_old_pattern() -> None:
    # given
    markups = _oracle_markups()

    # when
    mismatches = [m for m in markups if _without_style_bodies(m) != _REFERENCE_STYLE_BODY.sub(r"\1\2", m)]

    # then
    assert mismatches == []


def test_password_inputs_are_found_exactly_like_the_old_pattern() -> None:
    # given
    markups = _oracle_markups()

    # when
    mismatches = [m for m in markups if has_password_input(m) != bool(_REFERENCE_PASSWORD_INPUT.search(m))]

    # then
    assert mismatches == []


@pytest.mark.parametrize("piece", ["<style>", "<input ", "<style", "<input type="])
def test_half_a_megabyte_of_unclosed_tags_is_judged_within_a_second(piece: str) -> None:
    # given
    html = piece * (_PAGE_BYTES // len(piece))

    # when
    started = time.perf_counter()
    verdict = assess(200, html, record_metrics=False)
    ChallengeDetector.login_wall_verdict(
        verdict,
        html,
        requested_url="https://www.example.com/r/programming/",
        final_url="https://www.example.com/login",
    )
    elapsed = time.perf_counter() - started

    # then
    assert elapsed < _SCAN_BUDGET_SECONDS


def _title_page(count: int) -> str:
    return "<title>" * count


@pytest.mark.parametrize(
    "page",
    ["<title>" * (50_000 // len("<title>")), "<title" * (50_000 // len("<title")), "<title>x</title>" * 3000],
    ids=["open-tags", "unclosed-tag-names", "closed-titles"],
)
def test_login_title_scan_of_many_title_tags_is_linear(page: str) -> None:
    # given
    started = time.perf_counter()

    # when
    found = ChallengeDetector.is_login_required(page)

    # then
    assert time.perf_counter() - started < _SCAN_BUDGET_SECONDS
    assert found is False


def _reference_login_required(html: str) -> bool:
    return any(
        ChallengeDetector.is_login_required(f"<title>{match.group(1)}</title>")
        for match in _REFERENCE_TITLE.finditer(html)
    )


@pytest.mark.parametrize("markup", _oracle_markups()[:600])
def test_login_title_scan_matches_the_old_pattern(markup: str) -> None:
    # then
    assert ChallengeDetector.is_login_required(markup) is _reference_login_required(markup)


@pytest.mark.parametrize(
    "page",
    [
        '="' * (_PAGE_BYTES // 2),
        "= " * (_PAGE_BYTES // 2),
        "</style " * (_PAGE_BYTES // 8),
        "<input type = " * (_PAGE_BYTES // 14),
    ],
    ids=["data-uri-attributes", "equal-signs", "style-closers", "input-types"],
)
def test_the_remaining_signal_patterns_stay_linear_on_site_markup(page: str) -> None:
    # given
    started = time.perf_counter()

    # when
    assess(200, page, record_metrics=False)
    has_password_input(page)

    # then
    assert time.perf_counter() - started < _SCAN_BUDGET_SECONDS * 2
