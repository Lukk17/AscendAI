import re
from typing import Final

PROFILE_PATTERN: Final[str] = r"[A-Za-z0-9_-]{1,64}"


def is_valid_profile(value: str) -> bool:
    """True when the whole of *value* matches PROFILE_PATTERN."""
    return re.fullmatch(PROFILE_PATTERN, value) is not None
