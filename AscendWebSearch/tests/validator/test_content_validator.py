from unittest.mock import patch

from src.validator.content_validator import ContentValidator


def test_validate_passes_for_quality_long_content():
    words = [f"word{i}" for i in range(210)]
    content = " ".join(words)
    assert ContentValidator().validate(content) is True


def test_validate_fails_for_empty_string():
    assert ContentValidator().validate("") is False


def test_validate_fails_for_whitespace_only():
    assert ContentValidator().validate("   \t\n") is False


def test_validate_fails_for_short_text():
    assert ContentValidator().validate("only one") is False


def test_validate_fails_on_error_keyword():
    text = " ".join(["filler"] * 30) + " Access Denied " + " ".join(["more"] * 30)
    assert ContentValidator().validate(text) is False


def test_validate_passes_when_textstat_raises():
    words = [f"word{i}" for i in range(60)]
    content = " ".join(words)
    with patch(
        "src.validator.content_validator._lexicon_count",
        side_effect=RuntimeError("nope"),
    ):
        assert ContentValidator().validate(content) is True


def test_validate_fails_when_low_lexicon_and_low_flesch():
    # 11 unique words to pass the length gate, lexicon_count < min and flesch < threshold
    content = "one two three four five six seven eight nine ten eleven"
    with (
        patch("src.validator.content_validator._lexicon_count", return_value=5),
        patch("src.validator.content_validator._flesch_reading_ease", return_value=5.0),
    ):
        assert ContentValidator().validate(content) is False


def test_validate_fails_on_repetition():
    # 51 identical words -> TTR < 0.1 -> repetitive
    content = " ".join(["foo"] * 51)
    with (
        patch("src.validator.content_validator._lexicon_count", return_value=51),
        patch("src.validator.content_validator._flesch_reading_ease", return_value=60.0),
    ):
        assert ContentValidator().validate(content) is False
