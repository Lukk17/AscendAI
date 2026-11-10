"""The session profile and session address types every REST model and MCP tool shares."""

import logging
from typing import Annotated, Final
from urllib.parse import urlsplit

from fastmcp.exceptions import FastMCPError
from pydantic import AfterValidator, AnyUrl, HttpUrl, StringConstraints, TypeAdapter

from src.session.profile_pattern import PROFILE_PATTERN, is_valid_profile

MAX_URL_LENGTH: Final[int] = TypeAdapter(HttpUrl).json_schema()["maxLength"]


class InvalidProfileError(FastMCPError):
    """A profile outside PROFILE_PATTERN. Pydantic passes it out of a validator unwrapped."""

    def __init__(self, message: str) -> None:
        super().__init__(message, log_level=logging.DEBUG)


def check_profile(value: str) -> str:
    """Return *value* unchanged.

    Raises:
        InvalidProfileError: when *value* does not match PROFILE_PATTERN.
    """
    if not is_valid_profile(value):
        raise InvalidProfileError(f"profile must match {PROFILE_PATTERN}")

    return value


def _read_profile(value: str) -> str | None:
    return check_profile(value) if value else None


Profile = Annotated[str, AfterValidator(_read_profile)]


def refuse_user_info(url: str) -> str:
    """Return *url* unchanged.

    Raises:
        ValueError: when *url* carries user info before its host.
    """
    if "@" in urlsplit(url).netloc:
        raise ValueError("url must not carry user info before the host")

    return url


def _refuse_http_url_user_info(url: HttpUrl) -> HttpUrl:
    refuse_user_info(str(url))

    return url


def _refuse_long_seed(url: AnyUrl) -> AnyUrl:
    if len(str(url)) > MAX_URL_LENGTH:
        raise ValueError(f"url must have at most {MAX_URL_LENGTH} characters")

    return url


ReadUrl = Annotated[str, StringConstraints(max_length=MAX_URL_LENGTH)]

SeedUrl = Annotated[AnyUrl, AfterValidator(_refuse_long_seed)]

SessionUrl = Annotated[ReadUrl, AfterValidator(refuse_user_info)]

SessionHttpUrl = Annotated[HttpUrl, AfterValidator(_refuse_http_url_user_info)]
