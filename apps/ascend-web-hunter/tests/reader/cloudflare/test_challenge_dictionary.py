"""Catalogue contract for the challenge dictionary (tasks 2.1, 2.3, 5.5).

The file is the one maintained catalogue: vendors with a source and a
verified_on date per marker, phrases with a provenance per translation, and
the login title patterns verbatim. Language codes are the thirty of design
Decision 4; the table printed here is committed into docs/challenge-detection.md.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from src.reader.cloudflare import challenge_signals
from src.reader.cloudflare.challenge_signals import load_catalogue, normalise_phrase

_CATALOGUE_PATH = Path("src/reader/cloudflare/challenge_dictionary.json")

_PHRASE_IDS = [
    "cf_just_a_moment",
    "cf_checking_connection",
    "cf_attention_required",
    "cf_verify_human",
    "generic_prove_humanity",
    "generic_verify_you_are_human",
    "generic_not_a_robot",
    "generic_enable_js_adblock",
    "datadome_captcha",
    "imperva_pardon_interruption",
    "amazon_type_characters",
    "amazon_enter_characters",
    "amazon_continue_shopping",
    "akamai_access_denied",
    "perimeterx_automation_tools",
    "ddosguard_title",
]

_LANGUAGE_CODES = [
    "bg",
    "hr",
    "cs",
    "da",
    "nl",
    "en",
    "et",
    "fi",
    "fr",
    "de",
    "el",
    "hu",
    "it",
    "lv",
    "lt",
    "pl",
    "pt",
    "ro",
    "sk",
    "sl",
    "es",
    "sv",
    "uk",
    "ru",
    "tr",
    "ja",
    "ko",
    "zh-Hans",
    "zh-Hant",
    "ar",
]

_OLD_DICTIONARY_STRINGS = [
    "arkoselabs.com",
    "recaptcha/api.js",
    "hcaptcha.com/1/api.js",
    "perimeterx.net",
    "Prove your humanity",
    "Pardon Our Interruption",
    "Please verify you are a human",
    "Checking if the site connection is secure",
    "Just a moment...",
    "Attention Required!",
    "DataDome CAPTCHA",
    "Please enable JS and disable any ad blocker",
    "Sorry, we just need to make sure you're not a robot",
    "Potwierdź, że nie jesteś robotem",
    "/errors_page/validateCaptcha",
    "sign in",
    "log in",
    "login",
    "sign into",
    "create account",
]


def _raw() -> dict[str, Any]:
    # given
    data: dict[str, Any] = json.loads(_CATALOGUE_PATH.read_text(encoding="utf-8"))
    return data


def test_every_marker_has_source_and_verified_on() -> None:
    # given
    raw = _raw()

    # when / then
    assert raw["vendors"], "catalogue must name at least one vendor"
    for vendor, entry in raw["vendors"].items():
        assert entry["markers"], f"vendor {vendor} must carry at least one marker"
        for marker in entry["markers"]:
            assert marker.get("source"), f"marker {marker} of {vendor} needs a source URL"
            assert str(marker["source"]).startswith("http"), (
                f"marker {marker} of {vendor} needs a non-empty source URL"
            )
            assert marker.get("verified_on"), f"marker {marker} of {vendor} needs a verified_on date"


def test_every_phrase_id_present_exactly_once() -> None:
    # given
    raw = _raw()

    # when / then
    assert sorted(raw["phrases"]) == sorted(_PHRASE_IDS)


def test_every_translation_has_provenance() -> None:
    # given
    raw = _raw()

    # when / then
    for phrase_id, entry in raw["phrases"].items():
        assert entry.get("en"), f"phrase {phrase_id} needs its canonical English"
        assert entry.get("provenance"), f"phrase {phrase_id} needs a provenance"
        for lang, item in entry.get("translations", {}).items():
            assert item.get("text"), f"phrase {phrase_id} language {lang} needs its text"
            assert item.get("provenance"), f"phrase {phrase_id} language {lang} needs a provenance"


def test_old_dictionary_strings_all_carried() -> None:
    # given
    raw = _raw()
    marker_texts = [
        str(marker.get("match", {})) for entry in raw["vendors"].values() for marker in entry["markers"]
    ]
    catalogue_phrases = [entry["en"] for entry in raw["phrases"].values()]
    for entry in raw["phrases"].values():
        catalogue_phrases.extend(item["text"] for item in entry.get("translations", {}).values())
    normalised_catalogue = [normalise_phrase(text) for text in catalogue_phrases]
    login_patterns = list(raw["login_title_patterns"])

    # when / then
    for old in _OLD_DICTIONARY_STRINGS:
        in_markers = any(old.casefold() in text.casefold() for text in marker_texts)
        in_phrases = normalise_phrase(old) in normalised_catalogue
        assert in_markers or in_phrases or old in login_patterns, (
            f"old dictionary string {old!r} is missing from the catalogue"
        )


def test_login_title_patterns_verbatim() -> None:
    # given
    raw = _raw()

    # when / then
    assert list(raw["login_title_patterns"]) == ["sign in", "log in", "login", "sign into", "create account"]


def test_marker_match_key_shapes() -> None:
    """Each signal's markers carry the match key the signal reads, so the loader
    can resolve them once at import without a silent fallback."""
    # given
    raw = _raw()

    # when / then
    for vendor, entry in raw["vendors"].items():
        for marker in entry["markers"]:
            match = marker.get("match", {})
            if marker["signal"] in ("vendor_script", "interstitial_structure"):
                assert "prefix" in match, f"marker {marker} of {vendor} needs a prefix"
            elif marker["signal"] == "definitive_header":
                assert "header" in match, f"marker {marker} of {vendor} needs a header"
            elif marker["signal"] == "vendor_presence":
                assert "header" in match or "cookie" in match, (
                    f"marker {marker} of {vendor} needs a header or a cookie"
                )
            elif marker["signal"] in ("captcha_element", "captcha_input"):
                assert "attribute" in match, f"marker {marker} of {vendor} needs an attribute"


def test_missing_catalogue_raises_naming_path(tmp_path: Path) -> None:
    # given
    missing = tmp_path / "challenge_dictionary.json"

    # when / then
    with pytest.raises(FileNotFoundError, match=str(missing).replace("\\", "\\\\")):
        load_catalogue(missing)


def test_malformed_catalogue_raises_naming_path(tmp_path: Path) -> None:
    # given
    broken = tmp_path / "challenge_dictionary.json"
    broken.write_text("{not json", encoding="utf-8")

    # when / then
    with pytest.raises(ValueError, match=str(broken).replace("\\", "\\\\")):
        load_catalogue(broken)


def test_catalogue_missing_sections_raise_naming_path(tmp_path: Path) -> None:
    # given
    broken = tmp_path / "challenge_dictionary.json"
    broken.write_text('{"vendors": {}}', encoding="utf-8")

    # when / then
    with pytest.raises(ValueError, match=str(broken).replace("\\", "\\\\")):
        load_catalogue(broken)


def test_phrase_by_language_table(capsys: pytest.CaptureFixture[str]) -> None:
    """Print the phrase by language table committed into docs/challenge-detection.md."""
    # given
    raw = _raw()

    # when
    header = "phrase | " + " | ".join(_LANGUAGE_CODES)
    print(header)
    for phrase_id in _PHRASE_IDS:
        translations = raw["phrases"][phrase_id].get("translations", {})
        row = phrase_id + " | " + " | ".join("x" if lang in translations else "" for lang in _LANGUAGE_CODES)
        print(row)

    # then
    out = capsys.readouterr().out
    assert len(_LANGUAGE_CODES) == 30
    assert len(_PHRASE_IDS) == 16
    assert challenge_signals._NORMALISED_PHRASES
    for phrase_id in _PHRASE_IDS:
        assert phrase_id in out
