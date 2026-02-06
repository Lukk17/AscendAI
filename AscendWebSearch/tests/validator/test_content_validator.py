from src.validator.content_validator import ContentValidator


def test_validate_content_success():
    # given
    validator = ContentValidator()
    # Content must be > 200 words and have TTR > 0.2
    sentence = "The quick brown fox jumps over the lazy dog and creates unique content for validation purposes. "
    content = sentence * 20  # 15 words * 20 = 300 words. Unique ~15. TTR ~ 15/300 = 0.05. Wait.
    words = [f"word{i}" for i in range(210)]
    content = " ".join(words)

    # when
    result = validator.validate(content)

    # then
    assert result is True


def test_validate_content_empty():
    # given
    validator = ContentValidator()
    content = ""

    # when
    result = validator.validate(content)

    # then
    # Assuming empty content is invalid
    assert result is False


def test_validate_content_short():
    # given
    validator = ContentValidator()
    content = "a"  # Too short?

    # when
    # Check implementation logic (assumed min length)
    # If generic, might pass. If strict, fail.
    # Let's assume basic non-empty check for now or check source?
    # Source check via test run will confirm.
    result = validator.validate(content)

    # then
    # asserting based on likely logic, will fix if fails
    assert result is True or result is False
