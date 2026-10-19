"""Scored challenge-wall verdict shared by every fetch tier and the NoVNC monitor.

One decision function, one score and one threshold (design Decision 1 and
Decision 2 of ``detect-challenge-walls-in-any-language``). Family A (vendor
signatures) and family B (HTTP evidence) are language-independent; family C
(page structure) reads attribute values and element names only; family D
(content shape) reads one trafilatura extraction; family E (phrases) is the
supplement, matched after normalisation.
"""

import json
import logging
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import lxml.html
import trafilatura

from src.config.config import settings
from src.observability.metrics import (
    CHALLENGE_SCORE,
    CHALLENGE_SIGNALS_FIRED_TOTAL,
    CHALLENGE_VERDICTS_TOTAL,
)

logger = logging.getLogger(__name__)

_CATALOGUE_PATH = Path(__file__).parent / "challenge_dictionary.json"

_BLOCK_STATUSES = frozenset({403, 429, 503})

_DEFINITIVE_SIGNALS = frozenset({"definitive_header", "status_empty_body"})


def normalise_phrase(value: str) -> str:
    """Normalise a phrase for catalogue loading and page matching alike.

    NFKC, casefold, punctuation stripped, whitespace collapsed, so
    ``Just a moment...``, ``Just a moment...`` and ``JUST A MOMENT`` are one
    string. The loader and the matcher share this function so they can never
    disagree.
    """
    folded = unicodedata.normalize("NFKC", value).casefold()
    stripped = "".join(ch for ch in folded if not unicodedata.category(ch).startswith("P"))
    return " ".join(stripped.split())


def _normalise_marker(value: str) -> str:
    """Lower-case a catalogue marker for comparison against lowered input."""
    return value.casefold()


@dataclass(frozen=True)
class FiredSignal:
    id: str
    family: str
    weight: int
    vendor: str | None
    evidence: str


@dataclass(frozen=True)
class ChallengeVerdict:
    score: int
    threshold: int
    signals: tuple[FiredSignal, ...]
    vendor: str | None
    wall: bool
    has_content: bool
    intervention_type: str

    @property
    def accepted(self) -> bool:
        return not self.wall and self.has_content


def _signal_weight(signal_id: str) -> int:
    return int(getattr(settings, f"CHALLENGE_WEIGHT_{signal_id.upper()}"))


@dataclass(frozen=True)
class _Catalogue:
    vendors: dict[str, dict[str, Any]]
    phrases: dict[str, dict[str, Any]]
    login_title_patterns: tuple[str, ...]


def load_catalogue(path: str | Path = _CATALOGUE_PATH) -> _Catalogue:
    """Load the challenge catalogue, failing loudly on a missing or malformed file."""
    catalogue_path = Path(path)
    try:
        raw = json.loads(catalogue_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"challenge catalogue not found at {catalogue_path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"challenge catalogue at {catalogue_path} is malformed: {exc}") from exc
    try:
        vendors = raw["vendors"]
        phrases = raw["phrases"]
        login_title_patterns = tuple(raw["login_title_patterns"])
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"challenge catalogue at {catalogue_path} is malformed: {exc}") from exc
    return _Catalogue(vendors=vendors, phrases=phrases, login_title_patterns=login_title_patterns)


_CATALOGUE = load_catalogue()

_VENDOR_NAMES: tuple[str, ...] = tuple(_CATALOGUE.vendors)


def _normalised_phrases() -> dict[str, dict[str, Any]]:
    """Catalogue phrases normalised once at load time with the matcher function."""
    normalised: dict[str, dict[str, Any]] = {}
    for phrase_id, entry in _CATALOGUE.phrases.items():
        translations = {
            lang: {
                "text": item["text"],
                "normalised": normalise_phrase(item["text"]),
                "provenance": item["provenance"],
            }
            for lang, item in entry.get("translations", {}).items()
        }
        normalised[phrase_id] = {
            "normalised_en": normalise_phrase(entry["en"]),
            "match": entry.get("match", ["body"]),
            "translations": translations,
        }
    return normalised


_NORMALISED_PHRASES = _normalised_phrases()


def _lower_headers(headers: Any) -> dict[str, str]:
    if not headers:
        return {}
    lowered: dict[str, str] = {}
    for name, value in dict(headers).items():
        lowered[str(name).casefold()] = str(value).casefold()
    return lowered


def _lower_cookie_names(cookie_names: Sequence[str] | None) -> list[str]:
    if not cookie_names:
        return []
    return [str(name).casefold() for name in cookie_names]


def _match_header(marker: str, headers: dict[str, str]) -> bool:
    text = _normalise_marker(marker)
    name, sep, expected = text.partition(":")
    if not sep:
        return text in headers
    name = name.strip()
    expected = expected.strip()
    if name not in headers:
        return False
    return expected in headers[name]


def _match_cookie(marker: str, cookie_names: list[str]) -> bool:
    return any(_normalise_marker(marker) in name for name in cookie_names)


def _markers_of(signal_id: str) -> tuple[tuple[str, dict[str, Any]], ...]:
    """(vendor, match) pairs of one signal, resolved once at import.

    A marker without its ``match`` mapping fails here, at import time, instead
    of silently matching nothing at request time.
    """
    return tuple(
        (vendor, marker["match"])
        for vendor, entry in _CATALOGUE.vendors.items()
        for marker in entry.get("markers", [])
        if marker.get("signal") == signal_id
    )


_DEFINITIVE_HEADER_MARKERS = _markers_of("definitive_header")
_VENDOR_SCRIPT_MARKERS = _markers_of("vendor_script")
_VENDOR_PRESENCE_MARKERS = _markers_of("vendor_presence")
_INTERSTITIAL_PREFIX_MARKERS: tuple[tuple[str, str], ...] = tuple(
    (vendor, match["prefix"]) for vendor, match in _markers_of("interstitial_structure")
)
_CAPTCHA_ATTRIBUTE_MARKERS: tuple[str, ...] = tuple(
    match["attribute"] for _vendor, match in _markers_of("captcha_element")
)


def _definitive_header_signal(
    headers: dict[str, str],
) -> FiredSignal | None:
    for vendor, match in _DEFINITIVE_HEADER_MARKERS:
        if "header" in match and _match_header(match["header"], headers):
            return FiredSignal(
                id="definitive_header",
                family="vendor",
                weight=_signal_weight("definitive_header"),
                vendor=vendor,
                evidence=match["header"],
            )
    return None


def _vendor_presence_signal(headers: dict[str, str], cookie_names: list[str]) -> FiredSignal | None:
    for vendor, match in _VENDOR_PRESENCE_MARKERS:
        if "header" in match and _match_header(match["header"], headers):
            return FiredSignal(
                id="vendor_presence",
                family="vendor",
                weight=_signal_weight("vendor_presence"),
                vendor=vendor,
                evidence=match["header"],
            )
        if "cookie" in match and _match_cookie(match["cookie"], cookie_names):
            return FiredSignal(
                id="vendor_presence",
                family="vendor",
                weight=_signal_weight("vendor_presence"),
                vendor=vendor,
                evidence=match["cookie"],
            )
    return None


def _vendor_script_signal(prefix: str) -> FiredSignal | None:
    for vendor, match in _VENDOR_SCRIPT_MARKERS:
        if "prefix" in match and _normalise_marker(match["prefix"]) in prefix:
            return FiredSignal(
                id="vendor_script",
                family="vendor",
                weight=_signal_weight("vendor_script"),
                vendor=vendor,
                evidence=match["prefix"],
            )
    return None


def _interstitial_structure_signal(prefix: str, status_code: int) -> FiredSignal | None:
    for vendor, text in _INTERSTITIAL_PREFIX_MARKERS:
        lowered = _normalise_marker(text)
        if vendor == "akamai" and "reference #18." in lowered and status_code != 403:
            continue
        if lowered in prefix:
            return FiredSignal(
                id="interstitial_structure",
                family="vendor",
                weight=_signal_weight("interstitial_structure"),
                vendor=vendor,
                evidence=text,
            )
    return None


def _status_signals(status_code: int, html_length: int) -> list[FiredSignal]:
    if status_code not in _BLOCK_STATUSES:
        return []
    if html_length == 0:
        return [
            FiredSignal(
                id="status_empty_body",
                family="http",
                weight=_signal_weight("status_empty_body"),
                vendor=None,
                evidence=str(status_code),
            )
        ]
    if html_length < settings.CHALLENGE_WALL_MAX_BYTES:
        return [
            FiredSignal(
                id="status_small_body",
                family="http",
                weight=_signal_weight("status_small_body"),
                vendor=None,
                evidence=str(status_code),
            )
        ]
    return [
        FiredSignal(
            id="status_large_body",
            family="http",
            weight=_signal_weight("status_large_body"),
            vendor=None,
            evidence=str(status_code),
        )
    ]


def _parse_tree(prefix: str) -> tuple[Any | None, bool]:
    if not prefix:
        return None, True
    try:
        return lxml.html.fromstring(prefix), False
    except Exception:
        return None, True


def _visible_words(text: str) -> list[str]:
    return text.split()


def _captcha_input_signal(tree: Any) -> FiredSignal | None:
    for element in tree.iter("input", "textarea"):
        for attr in ("name", "id", "autocomplete"):
            value = (element.get(attr) or "").casefold()
            if "captcha" in value:
                return FiredSignal(
                    id="captcha_input",
                    family="structure",
                    weight=_signal_weight("captcha_input"),
                    vendor=None,
                    evidence=f"{element.tag} {attr}",
                )
    return None


def _element_has_captcha_marker(element: Any) -> str | None:
    for attr in ("class", "id"):
        value = (element.get(attr) or "").casefold()
        if "captcha" in value or value.startswith("geetest_"):
            return f"{element.tag} {attr}"
        for attribute in _CAPTCHA_ATTRIBUTE_MARKERS:
            if _normalise_marker(attribute) in value:
                return f"{element.tag} {attr}"
    return None


def _captcha_element_signal(tree: Any) -> FiredSignal | None:
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        found = _element_has_captcha_marker(element)
        if found is not None:
            return FiredSignal(
                id="captcha_element",
                family="structure",
                weight=_signal_weight("captcha_element"),
                vendor=None,
                evidence=found,
            )
        if element.tag in ("img", "canvas", "iframe"):
            for attr in ("src", "id"):
                value = (element.get(attr) or "").casefold()
                if "captcha" in value:
                    return FiredSignal(
                        id="captcha_element",
                        family="structure",
                        weight=_signal_weight("captcha_element"),
                        vendor=None,
                        evidence=f"{element.tag} {attr}",
                    )
        src = (element.get("src") or "").casefold()
        if src:
            for attribute in _CAPTCHA_ATTRIBUTE_MARKERS:
                if _normalise_marker(attribute) in src:
                    return FiredSignal(
                        id="captcha_element",
                        family="structure",
                        weight=_signal_weight("captcha_element"),
                        vendor=None,
                        evidence=f"{element.tag} src",
                    )
    return None


def _form_texts(tree: Any) -> tuple[list[str], str]:
    bodies = tree.xpath("//body")
    whole = bodies[0].text_content() if bodies else tree.text_content()
    forms = [form.text_content() for form in tree.xpath("//form")]
    return forms, whole


def _form_dominance_signal(tree: Any) -> FiredSignal | None:
    forms, whole = _form_texts(tree)
    if not forms:
        return None
    whole_words = _visible_words(whole)
    if not whole_words:
        return None
    in_forms = sum(len(_visible_words(text)) for text in forms)
    if in_forms / len(whole_words) >= settings.CHALLENGE_FORM_DOMINANCE_RATIO:
        return FiredSignal(
            id="form_dominance",
            family="structure",
            weight=_signal_weight("form_dominance"),
            vendor=None,
            evidence="form",
        )
    return None


def _dominant_form_has_password(tree: Any) -> bool:
    forms = tree.xpath("//form")
    if not forms:
        return False

    def _word_count(form: Any) -> int:
        return len(_visible_words(form.text_content()))

    dominant = max(forms, key=_word_count)
    return any((element.get("type") or "").casefold() == "password" for element in dominant.iter("input"))


def _script_only_body_signal(tree: Any) -> FiredSignal | None:
    for meta in tree.xpath("//meta"):
        if (meta.get("http-equiv") or "").casefold() == "refresh":
            return FiredSignal(
                id="script_only_body",
                family="structure",
                weight=_signal_weight("script_only_body"),
                vendor=None,
                evidence="meta refresh",
            )
    bodies = tree.xpath("//body")
    body_text = bodies[0].text_content() if bodies else ""
    if (
        len(_visible_words(body_text)) < settings.VALIDATION_MIN_WORDS
        and tree.xpath("//script")
        and tree.xpath("//noscript")
    ):
        return FiredSignal(
            id="script_only_body",
            family="structure",
            weight=_signal_weight("script_only_body"),
            vendor=None,
            evidence="script noscript",
        )
    return None


def _shape_signals(
    extracted_words: list[str] | None,
    html_length: int,
    tree: Any | None,
) -> list[FiredSignal]:
    fired: list[FiredSignal] = []
    if extracted_words is None:
        return fired
    words = len(extracted_words)
    kilobytes = html_length / 1024 if html_length > 0 else 0
    if kilobytes > 0 and words / kilobytes < settings.CHALLENGE_MIN_WORDS_PER_KB:
        fired.append(
            FiredSignal(
                id="thin_text",
                family="shape",
                weight=_signal_weight("thin_text"),
                vendor=None,
                evidence="words-per-kb",
            )
        )
    link_count = len(tree.xpath("//a[@href]")) if tree is not None else 0
    if link_count < settings.CHALLENGE_THIN_LINK_COUNT:
        fired.append(
            FiredSignal(
                id="few_links",
                family="shape",
                weight=_signal_weight("few_links"),
                vendor=None,
                evidence="anchors",
            )
        )
    has_article = tree is not None and bool(tree.xpath("//article | //main"))
    if not has_article and words < settings.CHALLENGE_RICH_CONTENT_WORDS:
        fired.append(
            FiredSignal(
                id="no_article",
                family="shape",
                weight=_signal_weight("no_article"),
                vendor=None,
                evidence="no-article",
            )
        )
    if words >= settings.CHALLENGE_RICH_CONTENT_WORDS:
        fired.append(
            FiredSignal(
                id="rich_content",
                family="shape",
                weight=_signal_weight("rich_content"),
                vendor=None,
                evidence="rich-content",
            )
        )
    if link_count >= settings.CHALLENGE_RICH_LINK_COUNT:
        fired.append(
            FiredSignal(
                id="many_links",
                family="shape",
                weight=_signal_weight("many_links"),
                vendor=None,
                evidence="anchors",
            )
        )
    return fired


def _phrase_variants(phrase_id: str) -> list[tuple[str, str]]:
    entry = _NORMALISED_PHRASES[phrase_id]
    variants = [(entry["normalised_en"], "en")]
    for lang, item in entry["translations"].items():
        variants.append((item["normalised"], lang))
    return variants


def _phrase_title_signal(title: str) -> FiredSignal | None:
    if not title:
        return None
    for phrase_id, entry in _NORMALISED_PHRASES.items():
        if "title" not in entry["match"]:
            continue
        for variant, _lang in _phrase_variants(phrase_id):
            if title == variant or title.startswith(variant):
                return FiredSignal(
                    id="phrase_title",
                    family="phrase",
                    weight=_signal_weight("phrase_title"),
                    vendor=None,
                    evidence=phrase_id,
                )
    return None


def _phrase_body_signal(visible_text: str) -> FiredSignal | None:
    if not visible_text:
        return None
    for phrase_id, entry in _NORMALISED_PHRASES.items():
        if "body" not in entry["match"]:
            continue
        for variant, _lang in _phrase_variants(phrase_id):
            if variant in visible_text:
                return FiredSignal(
                    id="phrase_body",
                    family="phrase",
                    weight=_signal_weight("phrase_body"),
                    vendor=None,
                    evidence=phrase_id,
                )
    return None


def _family_a_signals(
    header_map: dict[str, str],
    cookie_names: list[str],
    lowered_prefix: str,
    status_code: int,
) -> list[FiredSignal]:
    """Family A: vendor signatures over the header map, cookie names and prefix."""
    return [
        signal
        for signal in (
            _definitive_header_signal(header_map),
            _vendor_script_signal(lowered_prefix),
            _vendor_presence_signal(header_map, cookie_names),
            _interstitial_structure_signal(lowered_prefix, status_code),
        )
        if signal is not None
    ]


def _family_c_signals(tree: Any) -> list[FiredSignal]:
    """Family C: page structure over the parsed prefix tree."""
    return [
        signal
        for signal in (
            _captcha_input_signal(tree),
            _captcha_element_signal(tree),
            _form_dominance_signal(tree),
            _script_only_body_signal(tree),
        )
        if signal is not None
    ]


def _page_texts(tree: Any) -> tuple[str, str]:
    """Normalised title hit and visible text of the prefix for family E."""
    titles = [normalise_phrase(t.text or "") for t in tree.xpath("//title") if t.text]
    bodies = tree.xpath("//body")
    whole = bodies[0].text_content() if bodies else tree.text_content()
    return next((t for t in titles if t), ""), normalise_phrase(whole)


def _family_e_signals(title_hit: str, visible_text: str) -> list[FiredSignal]:
    """Family E: catalogue phrases over the normalised title and visible text."""
    return [
        signal
        for signal in (_phrase_title_signal(title_hit), _phrase_body_signal(visible_text))
        if signal is not None
    ]


def set_cookie_names(headers: Any) -> list[str]:
    """Cookie names carried by set-cookie headers: every get_list entry when the
    header mapping keeps multiples, else the single combined value. Best effort:
    a combined value split on commas would cut Expires dates, so only the first
    name of a combined value is read."""
    raw_values: list[str] = []
    get_list = getattr(headers, "get_list", None)
    if callable(get_list):
        try:
            raw_values.extend(str(value) for value in get_list("set-cookie") or [])
        except Exception:
            raw_values = []
    if not raw_values and headers is not None:
        get = getattr(headers, "get", None)
        single = get("set-cookie") if callable(get) else None
        if single:
            raw_values.append(str(single))
    names: list[str] = []
    for raw in raw_values:
        head = raw.split(";", 1)[0]
        if "=" in head:
            names.append(head.split("=", 1)[0].strip().casefold())
    return names


def verdict_label(verdict: ChallengeVerdict) -> str:
    """Bounded verdict label for the verdict counter: wall, content or no_content."""
    if verdict.wall:
        return "wall"
    return "content" if verdict.has_content else "no_content"


def as_login_verdict(verdict: ChallengeVerdict) -> ChallengeVerdict:
    """Escalate a title-login page that did not score a wall on its own: keep the
    scored verdict and take the login intervention type for the 428."""
    if verdict.intervention_type == "login":
        return verdict
    return replace(verdict, intervention_type="login")


def record_verdict(verdict: ChallengeVerdict, tier: str) -> None:
    """Count one verdict for the tier that called assess."""
    CHALLENGE_VERDICTS_TOTAL.labels(verdict=verdict_label(verdict), tier=tier).inc()


def log_verdict(verdict: ChallengeVerdict, tier: str, url: str) -> None:
    """One log line per verdict: INFO at or above half the threshold or on a
    wall, DEBUG otherwise. The signals field carries ids and weights only, never
    a page excerpt; evidence is the matched catalogue marker, never a response
    value."""
    signals = ",".join(f"{signal.id}:{signal.weight}" for signal in verdict.signals)
    message = (
        "Challenge verdict: wall=%s score=%d threshold=%d vendor=%s type=%s signals=%s tier=%s url=%s",
        verdict.wall,
        verdict.score,
        verdict.threshold,
        verdict.vendor,
        verdict.intervention_type,
        signals,
        tier,
        url,
    )
    if verdict.wall or verdict.score >= verdict.threshold / 2:
        logger.info(*message)
    else:
        logger.debug(*message)


def assess(
    status_code: int,
    html_content: str,
    headers: Any | None = None,
    cookie_names: Sequence[str] | None = (),
) -> ChallengeVerdict:
    """Score one fetched page and return the frozen verdict every tier shares."""
    html = html_content or ""
    prefix = html[: settings.CHALLENGE_DETECTION_MAX_BYTES]

    fired: list[FiredSignal] = []
    fired.extend(
        _family_a_signals(
            _lower_headers(headers),
            _lower_cookie_names(cookie_names),
            prefix.casefold(),
            status_code,
        )
    )
    fired.extend(_status_signals(status_code, len(html)))

    tree, parse_failed = _parse_tree(prefix)
    if parse_failed and prefix:
        fired.append(
            FiredSignal(
                id="parse_failed",
                family="structure",
                weight=0,
                vendor=None,
                evidence="parser",
            )
        )

    if tree is not None:
        fired.extend(_family_c_signals(tree))

    extracted_words: list[str] | None = None
    if len(html) <= settings.CHALLENGE_SHAPE_MAX_BYTES:
        extracted_words = _visible_words(trafilatura.extract(html) or "")

    title_hit, visible_text = _page_texts(tree) if tree is not None else ("", "")
    fired.extend(_family_e_signals(title_hit, visible_text))
    fired.extend(_shape_signals(extracted_words, len(html), tree))

    score = sum(signal.weight for signal in fired)
    threshold = settings.CHALLENGE_SCORE_THRESHOLD
    wall = score >= threshold or any(signal.id in _DEFINITIVE_SIGNALS for signal in fired)

    for signal in fired:
        CHALLENGE_SIGNALS_FIRED_TOTAL.labels(signal=signal.id, vendor=signal.vendor or "none").inc()
    CHALLENGE_SCORE.observe(score)

    if len(html) >= settings.CHALLENGE_WALL_MAX_BYTES:
        has_content = True
    elif not html:
        has_content = False
    else:
        words = len(extracted_words) if extracted_words is not None else 0
        has_content = words >= settings.VALIDATION_MIN_WORDS

    vendor = next((signal.vendor for signal in fired if signal.vendor), None)
    if tree is not None and wall and _dominant_form_has_password(tree):
        intervention_type = "login"
    else:
        intervention_type = "captcha"

    return ChallengeVerdict(
        score=score,
        threshold=threshold,
        signals=tuple(fired),
        vendor=vendor,
        wall=wall,
        has_content=has_content,
        intervention_type=intervention_type,
    )
