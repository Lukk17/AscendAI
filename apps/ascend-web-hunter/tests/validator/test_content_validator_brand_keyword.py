"""Brand-keyword behaviour of ContentValidator.

The widget homepages (friendlycaptcha, mtcaptcha, hcaptcha) carry hundreds of
words of real prose that names the page's own subject, so the bare "Captcha"
error keyword must not fail them: a wall signal needs wall context
(challenge/interstitial markers), not a bare brand token. True error pages,
which pair the token with wall context, must still fail.
"""

from src.validator.content_validator import ContentValidator


def _long_text(sentences: list[str]) -> str:
    # given
    fillers = [f"word{i}" for i in range(210)]
    return " ".join(fillers + sentences)


def test_validate_passes_for_hcaptcha_brand_prose() -> None:
    # given
    content = _long_text(
        [
            "hCaptcha delivers real-time bot detection and fraud prevention",
            "for websites apps and APIs while preserving user privacy.",
        ]
    )

    # when / then
    assert ContentValidator().validate(content) is True


def test_validate_passes_for_mtcaptcha_brand_prose() -> None:
    # given
    content = _long_text(
        [
            "MTCaptcha is an enterprise Captcha and bot protection platform",
            "that stops automated threats without capturing personal data.",
        ]
    )

    # when / then
    assert ContentValidator().validate(content) is True


def test_validate_passes_for_friendly_captcha_brand_prose() -> None:
    # given
    content = _long_text(
        [
            "Friendly Captcha respects your privacy and works automatically,",
            "a privacy-compliant Captcha alternative to traditional CAPTCHAs.",
        ]
    )

    # when / then
    assert ContentValidator().validate(content) is True


def test_validate_passes_for_captcha_subject_quoting_checkbox_label() -> None:
    # given: an article about captchas quoting a checkbox label, as served by
    # the article-ja counterexample (lowercase quote, no wall context).
    content = _long_text(
        [
            "Captcha designs changed after the press covered the verify you are human",
            "checkbox and the not a robot headline on vendor homepages.",
        ]
    )

    # when / then
    assert ContentValidator().validate(content) is True


def test_validate_fails_for_captcha_with_error_keyword_context() -> None:
    # given: the token paired with another error keyword is a wall signal.
    content = _long_text(
        [
            "Complete the Captcha Security Check below to continue.",
            "Ray ID 9f8e7d6c5b4a3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d.",
        ]
    )

    # when / then
    assert ContentValidator().validate(content) is False


def test_validate_fails_for_captcha_with_interstitial_phrase_context() -> None:
    # given: the token paired with a challenge/interstitial phrase is a wall signal.
    content = _long_text(
        [
            "Verify you are human by completing the Captcha challenge below",
            "to prove you are not facing an automated block page.",
        ]
    )

    # when / then
    assert ContentValidator().validate(content) is False
