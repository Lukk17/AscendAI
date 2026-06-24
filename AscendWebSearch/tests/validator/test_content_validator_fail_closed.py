"""Tests for ContentValidator fail-closed behaviour (task 6.4).

Before the fix, a textstat exception caused _passes_quality_metrics to return
True (fail-open), so junk/garbage content could pass validation.  After the fix
it returns False (fail-closed), causing the orchestrator to try the next tier.
"""

from unittest.mock import patch

from src.validator.content_validator import ContentValidator


def test_quality_metrics_exception_returns_false():
    """When textstat raises, the validator must fail closed (return False)."""
    # Build content that passes length/keyword checks but trips textstat.
    content = " ".join([f"word{i}" for i in range(20)])

    with patch(
        "src.validator.content_validator._lexicon_count",
        side_effect=RuntimeError("textstat boom"),
    ):
        result = ContentValidator().validate(content)

    assert result is False


def test_quality_metrics_flesch_exception_returns_false():
    """Flesch score raising must also fail closed."""
    content = " ".join([f"word{i}" for i in range(20)])

    with (
        patch("src.validator.content_validator._lexicon_count", return_value=20),
        patch("src.validator.content_validator._flesch_reading_ease", side_effect=ValueError("nan")),
    ):
        result = ContentValidator().validate(content)

    assert result is False
