"""The fixture corpus contract (tasks 8.1, 8.2, 8.6, 9.1) and the vendor label bound (7.3).

Every manifest entry carries its recorded status, headers and cookie names;
the test runs each fixture through `assess` and asserts the expected verdict,
the expected type and vendor, and the must and must-not signals. It prints the
fixture, score, margin and fired-signal table, with fixtures within twenty
points of the threshold under their own heading; that table is pasted into
design.md under Open Question 1.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from src.reader.cloudflare.challenge_signals import ChallengeVerdict, assess

_FIXTURES = Path("tests/fixtures/challenge_walls")
_MANIFEST = _FIXTURES / "manifest.json"

_REQUIRED_FIELDS = (
    "path",
    "vendor",
    "language",
    "kind",
    "status",
    "headers",
    "cookie_names",
    "source_url",
    "captured_on",
    "captured_with",
    "synthetic",
    "expected",
    "notes",
)

_REQUIRED_EXPECTED = ("wall", "intervention_type", "vendor", "signals_must_fire", "signals_must_not_fire")


def _manifest() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return data


def _verdict(entry: dict[str, Any]) -> ChallengeVerdict:
    html = (_FIXTURES / entry["path"]).read_text(encoding="utf-8")
    return assess(entry["status"], html, dict(entry["headers"]), list(entry["cookie_names"]))


def test_manifest_entries_have_required_fields_and_paths() -> None:
    # given
    manifest = _manifest()

    # when / then
    assert manifest, "the corpus must not be empty"
    for entry in manifest:
        for field in _REQUIRED_FIELDS:
            assert field in entry, f"{entry.get('path', entry)} is missing {field}"
        for field in _REQUIRED_EXPECTED:
            assert field in entry["expected"], f"{entry['path']} expected is missing {field}"
        assert (_FIXTURES / entry["path"]).exists(), f"{entry['path']} does not exist"
        assert entry["kind"] in ("wall", "counterexample")


@pytest.mark.parametrize("entry", _manifest(), ids=lambda entry: entry["path"])
def test_corpus_expectation(entry: dict[str, Any]) -> None:
    # given
    expected = entry["expected"]

    # when
    verdict = _verdict(entry)

    # then
    assert verdict.wall is expected["wall"], entry["path"]
    assert verdict.intervention_type == expected["intervention_type"], entry["path"]
    assert verdict.vendor == expected["vendor"], entry["path"]
    fired = {signal.id for signal in verdict.signals}
    for signal_id in expected["signals_must_fire"]:
        assert signal_id in fired, f"{entry['path']} must fire {signal_id}, fired {sorted(fired)}"
    for signal_id in expected["signals_must_not_fire"]:
        assert signal_id not in fired, f"{entry['path']} must not fire {signal_id}"


def test_wall_fixtures_have_positive_margin_and_counterexamples_negative() -> None:
    # given
    manifest = _manifest()

    # when / then
    for entry in manifest:
        verdict = _verdict(entry)
        margin = verdict.score - verdict.threshold if verdict.wall else verdict.threshold - verdict.score
        assert margin > 0, f"{entry['path']} score={verdict.score} wall={verdict.wall} has no margin"


def test_fixture_score_margin_and_signal_table(capsys: pytest.CaptureFixture[str]) -> None:
    """Print the fixture, score, margin and fired-signal table pasted into
    design.md under Open Question 1."""
    # given
    manifest = _manifest()

    # when
    rows = []
    for entry in manifest:
        verdict = _verdict(entry)
        margin = verdict.score - verdict.threshold if verdict.wall else verdict.threshold - verdict.score
        signals = ",".join(f"{signal.id}:{signal.weight}" for signal in verdict.signals)
        rows.append((entry["path"], verdict.score, margin, signals, verdict.wall))
    print("fixture | score | margin | wall | signals")
    for path, score, margin, signals, wall in rows:
        print(f"{path} | {score} | {margin} | {wall} | {signals}")
    print("near threshold (within 20 points):")
    near = [(path, score, margin) for path, score, margin, _, _ in rows if abs(margin) <= 20]
    for path, score, margin in near:
        print(f"{path} | {score} | {margin}")
    if not near:
        print("(none)")

    # then
    out = capsys.readouterr().out
    assert len(rows) == len(manifest)
    for entry in manifest:
        assert entry["path"] in out


def test_every_fixture_within_size_bound() -> None:
    # given
    manifest = _manifest()

    # when / then
    for entry in manifest:
        size = (_FIXTURES / entry["path"]).stat().st_size
        assert size <= 200 * 1024, f"{entry['path']} is {size} bytes, above 200 kilobytes"


def test_no_fixture_contains_cookie_value() -> None:
    # given
    import re

    from src.reader.cloudflare import challenge_signals

    catalogue = challenge_signals._CATALOGUE
    cookie_names = set()
    for vendor_entry in catalogue.vendors.values():
        for marker in vendor_entry.get("markers", []):
            match = marker.get("match", {})
            if "cookie" in match:
                cookie_names.add(str(match["cookie"]).lower())
    manifest = _manifest()

    # when / then
    for entry in manifest:
        low = (_FIXTURES / entry["path"]).read_text(encoding="utf-8").lower()
        for name in cookie_names:
            for found in re.finditer(re.escape(name) + r"=", low):
                value = low[found.end() : found.end() + 1]
                assert value == "" or not value.strip(), (
                    f"{entry['path']} contains cookie name {name} followed by a value"
                )


def test_every_synthetic_entry_listed_in_open_question_4() -> None:
    # given
    repo_root = Path(__file__).resolve().parents[5]
    design = (repo_root / "openspec/changes/detect-challenge-walls-in-any-language/design.md").read_text(
        encoding="utf-8"
    )

    def _norm(value: str) -> str:
        return value.casefold().replace("-", "").replace("_", "").replace(" ", "")

    question_4 = _norm(design.split("Open Question 4")[1].split("## Owner decisions")[0])
    manifest = _manifest()

    # when / then
    synthetics = [entry for entry in manifest if entry["synthetic"]]
    assert synthetics, "the corpus must carry the synthetic fixtures"
    for entry in synthetics:
        assert _norm(str(entry["vendor"])) in question_4, (
            f"{entry['path']} vendor {entry['vendor']} not listed in Open Question 4"
        )


def test_manifest_rejects_duplicate_vendor_with_synthetic() -> None:
    """The corpus README notes rule: no two entries for one vendor where one
    is synthetic. A manifest that breaks it is rejected."""
    # given
    from copy import deepcopy

    manifest = _manifest()
    assert not any(
        entry["synthetic"] and sum(1 for other in manifest if other["vendor"] == entry["vendor"]) > 1
        for entry in manifest
    )
    doubled = deepcopy(manifest)
    synthetic = next(entry for entry in doubled if entry["synthetic"])
    twin = deepcopy(synthetic)
    twin["path"] = "twin-" + str(twin["path"])
    doubled.append(twin)

    # when
    violations = [
        entry["vendor"]
        for entry in doubled
        if entry["synthetic"] and sum(1 for other in doubled if other["vendor"] == entry["vendor"]) > 1
    ]

    # then
    assert violations, "the notes rule must catch two entries for one vendor where one is synthetic"


def test_vendor_label_bounded_by_catalogue() -> None:
    # given
    from src.reader.cloudflare import challenge_signals

    catalogue_vendors = set(challenge_signals._CATALOGUE.vendors)
    manifest = _manifest()

    # when
    used = set()
    for entry in manifest:
        verdict = _verdict(entry)
        for signal in verdict.signals:
            used.add(signal.vendor or "none")
        used.add(verdict.vendor or "none")

    # then
    assert used <= (catalogue_vendors | {"none"}), used - (catalogue_vendors | {"none"})
