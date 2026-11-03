"""The fixture corpus contract (tasks 8.1, 8.2, 8.6, 8.7, 8.8, 9.1) and the vendor label bound (7.3).

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
        entry["synthetic"]
        and entry["kind"] == "wall"
        and sum(1 for other in manifest if other["vendor"] == entry["vendor"] and other["kind"] == "wall") > 1
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
        if entry["synthetic"]
        and entry["kind"] == "wall"
        and sum(1 for other in doubled if other["vendor"] == entry["vendor"] and other["kind"] == "wall") > 1
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


def _wall_languages(manifest: list[dict[str, Any]], vendor: str) -> list[str]:
    return sorted(
        {entry["language"] for entry in manifest if entry["vendor"] == vendor and entry["kind"] == "wall"}
    )


def _require_wall_languages(manifest: list[dict[str, Any]]) -> None:
    assert _wall_languages(manifest, "cloudflare") == ["ar", "de", "en", "fr", "ja", "pl"], (
        "the corpus must carry one Cloudflare wall fixture per captured language"
    )
    assert _wall_languages(manifest, "amazon") == ["de", "en", "es", "fr", "it", "ja", "pl", "sv"], (
        "the corpus must carry one Amazon wall fixture per captured language"
    )


def test_cloudflare_and_amazon_have_one_wall_fixture_per_captured_language() -> None:
    # given
    manifest = _manifest()

    # when / then the captured language sets hold
    _require_wall_languages(manifest)

    # and removing the sole wall of a covered language breaks the rule
    for path in ("amazon-de.html", "amazon-se.html", "cloudflare-rendered-pl.html"):
        reduced = [entry for entry in manifest if entry["path"] != path]
        with pytest.raises(AssertionError, match=r"one .* wall fixture per captured language"):
            _require_wall_languages(reduced)


def _shell_entry(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    shells = [entry for entry in manifest if entry["path"] == "script-shell.html"]
    assert len(shells) == 1, "the corpus must carry exactly one script-only shell fixture"
    return shells[0]


def test_script_shell_has_no_content_and_no_wall() -> None:
    # given
    manifest = _manifest()

    # when
    verdict = _verdict(_shell_entry(manifest))

    # then the shell is neither a wall nor content
    assert verdict.wall is False
    assert verdict.has_content is False

    # and removing the shell fixture breaks the rule
    reduced = [entry for entry in manifest if entry["path"] != "script-shell.html"]
    with pytest.raises(AssertionError, match="exactly one script-only shell"):
        _shell_entry(reduced)


def _vendors_missing_wall_fixtures(manifest: list[dict[str, Any]]) -> list[str]:
    from src.reader.cloudflare import challenge_signals

    walled = {entry["vendor"] for entry in manifest if entry["kind"] == "wall"}
    return sorted(vendor for vendor in challenge_signals._CATALOGUE.vendors if vendor not in walled)


# Vendors with no public thin wall page on 2026-10-26, one plain GET each in a
# throwaway container: demo.mtcaptcha.com is NXDOMAIN, www.mtcaptcha.com/demo
# answers 404, friendlycaptcha.com/demo/ redirects to the rich playground that
# is already the counterexample, github.com/signup answers a DataDome block
# with no Arkose script, and www.arkoselabs.com/request-demo answers 404.
# Evidence in the corpus README under Known gaps.
_KNOWN_VENDORS_WITHOUT_WALL: list[str] = []


def test_vendors_without_wall_fixtures_are_exactly_the_dated_gaps() -> None:
    # given
    manifest = _manifest()

    # when / then only the dated gaps lack a wall fixture
    assert _vendors_missing_wall_fixtures(manifest) == _KNOWN_VENDORS_WITHOUT_WALL

    # and removing a sole wall fixture opens a new gap
    reduced = [entry for entry in manifest if entry["path"] != "datadome-allegro.html"]
    assert "datadome" in _vendors_missing_wall_fixtures(reduced)


def _unfired_markers(manifest: list[dict[str, Any]]) -> list[str]:
    from src.config.config import settings
    from src.reader.cloudflare import challenge_signals

    assessed: list[tuple[str, str, dict[str, str]]] = []
    for entry in manifest:
        html = (_FIXTURES / entry["path"]).read_text(encoding="utf-8")
        prefix = html[: settings.CHALLENGE_DETECTION_MAX_BYTES].casefold()
        headers = {
            str(name).casefold(): str(value).casefold() for name, value in dict(entry["headers"]).items()
        }
        assessed.append((entry["path"], prefix, headers))
    statuses = {entry["path"]: entry["status"] for entry in manifest}

    def _fired(vendor: str, signal: str, match: dict[str, Any]) -> bool:
        if "prefix" in match:
            text = str(match["prefix"]).casefold()
            for path, prefix, _ in assessed:
                if vendor == "akamai" and statuses[path] != 403:
                    continue
                if text in prefix:
                    return True
            return False
        if "header" in match:
            name, _, expected = str(match["header"]).casefold().partition(":")
            name, expected = name.strip(), expected.strip()
            return any(
                name in headers and (not expected or expected in headers[name]) for _, _, headers in assessed
            )
        return False

    unfired = []
    for vendor, vendor_entry in challenge_signals._CATALOGUE.vendors.items():
        for marker in vendor_entry.get("markers", []):
            signal = marker.get("signal")
            if signal not in ("vendor_script", "interstitial_structure", "definitive_header"):
                continue
            match = marker.get("match", {})
            if not _fired(vendor, signal, match):
                unfired.append(f"{vendor} {signal} {match.get('prefix', match.get('header'))}")
    return sorted(unfired)


# Catalogue markers no honest capture fires on 2026-10-26: the seven retired
# Cloudflare element ids (only `Ray ID:` is served now), the DataDome tag
# script (block pages never include it; g2.com and github.com blocks verified),
# the alternate GeeTest, reCAPTCHA and MTCaptcha script hosts, the Friendly
# script (the playground loads it from a CDN path the catalogue excludes),
# the Arkose scripts (no public thin page serves them), the Amazon
# character-entry markers (all nine locales serve the button variant), and the
# AWS WAF captcha header variant. Evidence in the corpus README.
_KNOWN_UNFIRED_MARKERS = [
    "amazon interstitial_structure /errors/validateCaptcha",
    "amazon interstitial_structure captchacharacters",
    "amazon interstitial_structure opfcaptcha-prod.s3.amazonaws.com",
    "aws_waf definitive_header x-amzn-waf-action: captcha",
    "cloudflare interstitial_structure attack-box",
    "cloudflare interstitial_structure cf-challenge-running",
    "cloudflare interstitial_structure cf-please-wait",
    "cloudflare interstitial_structure challenge-spinner",
    "cloudflare interstitial_structure ray_id",
    "cloudflare interstitial_structure trk_jschal_js",
    "cloudflare interstitial_structure turnstile-wrapper",
    "datadome vendor_script js.datadome.co/",
    "datadome vendor_script js.datadome.co/tags.js",
    "geetest vendor_script gcaptcha4.geevisit.com",
    "geetest vendor_script gcaptcha4.gsensebot.com",
    "geetest vendor_script static.geevisit.com",
    "recaptcha vendor_script recaptcha.net/recaptcha/",
    "recaptcha vendor_script www.google.com/recaptcha/enterprise.js",
]


def test_unfired_markers_are_exactly_the_dated_gaps() -> None:
    # given
    manifest = _manifest()

    # when / then only the dated gaps stay unfired
    assert _unfired_markers(manifest) == _KNOWN_UNFIRED_MARKERS

    # and removing a fixture that solely fires a marker opens a new gap
    reduced = [entry for entry in manifest if entry["path"] != "nowsecure-rendered.html"]
    assert "cloudflare vendor_script challenges.cloudflare.com/turnstile/v0/api.js" in _unfired_markers(
        reduced
    )
    reduced = [entry for entry in manifest if entry["path"] != "datadome-allegro.html"]
    assert "datadome interstitial_structure captcha-delivery.com" in _unfired_markers(reduced)


def _unfired_translations(manifest: list[dict[str, Any]]) -> list[str]:
    from src.config.config import settings
    from src.reader.cloudflare import challenge_signals
    from src.reader.cloudflare.challenge_signals import _page_texts, _parse_tree, normalise_phrase

    texts = []
    for entry in manifest:
        html = (_FIXTURES / entry["path"]).read_text(encoding="utf-8")
        tree, _ = _parse_tree(html[: settings.CHALLENGE_DETECTION_MAX_BYTES])
        texts.append(_page_texts(tree) if tree is not None else ("", ""))

    def _fired(normalised: str, scope: list[str]) -> bool:
        for title, visible in texts:
            if "title" in scope and (title == normalised or title.startswith(normalised)):
                return True
            if "body" in scope and normalised in visible:
                return True
        return False

    unfired = []
    for phrase_id, phrase_entry in challenge_signals._CATALOGUE.phrases.items():
        scope = phrase_entry.get("match", ["body"])
        variants = [("en", phrase_entry["en"])]
        variants.extend((lang, item["text"]) for lang, item in phrase_entry.get("translations", {}).items())
        for lang, text in variants:
            if not _fired(normalise_phrase(text), scope):
                unfired.append(f"{phrase_id} {lang}")
    return sorted(unfired)


# Phrase translations no captured wall carries on 2026-10-26: the legacy
# English canonicals superseded by served copy, the character-entry Amazon
# phrases (button variant served), and the Polish not-a-robot translation.
_KNOWN_UNFIRED_TRANSLATIONS = [
    "amazon_enter_characters en",
    "amazon_type_characters en",
    "cf_attention_required en",
    "cf_checking_connection en",
    "datadome_captcha en",
    "generic_not_a_robot en",
    "generic_not_a_robot pl",
    "generic_prove_humanity en",
    "generic_verify_you_are_human en",
]


def test_unfired_translations_are_exactly_the_dated_gaps() -> None:
    # given
    manifest = _manifest()

    # when / then only the dated gaps stay unfired
    assert _unfired_translations(manifest) == _KNOWN_UNFIRED_TRANSLATIONS

    # and removing the sole wall of a covered translation opens a new gap
    reduced = [entry for entry in manifest if entry["path"] != "amazon-de.html"]
    assert "amazon_continue_shopping de" in _unfired_translations(reduced)
    reduced = [entry for entry in manifest if entry["path"] != "cloudflare-rendered-pl.html"]
    assert "cf_just_a_moment pl" in _unfired_translations(reduced)
