import os
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from limits import parse as parse_rate_limit
from pydantic import BeforeValidator, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from ascend_python_common.uri_guard import FetchPolicy


def _csv_to_tuple(value: object) -> object:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return value


CsvTuple = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_csv_to_tuple)]


def _upper_case(value: object) -> object:
    if isinstance(value, str):
        return value.upper()
    return value


LogLevel = Annotated[
    Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    BeforeValidator(_upper_case),
]


def _check_rate_limit(value: object) -> object:
    if isinstance(value, str):
        try:
            parse_rate_limit(value)
        except ValueError as exc:
            raise ValueError(f"invalid rate limit {value!r}") from exc
    return value


RateLimit = Annotated[str, BeforeValidator(_check_rate_limit)]


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(ge=1, le=65535)
    LOG_LEVEL: LogLevel = Field(default="INFO")
    LOG_FORMAT: Literal["json", "color"] = Field(default="json")
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = Field(default=None)
    RATE_LIMIT_DEFAULT: RateLimit
    READINESS_PROBE_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0)
    STARTUP_PROBE_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0)
    SECURITY_HSTS_MAX_AGE_SECONDS: int = Field(default=63072000, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _refuse_legacy_allow_list(cls, data: object) -> object:
        if "MCP_ALLOWED_HOSTS" in os.environ:
            raise ValueError("MCP_ALLOWED_HOSTS is set; use ALLOWED_PRIVATE_HOSTS instead")
        return data

    @field_validator("OTEL_EXPORTER_OTLP_ENDPOINT")
    @classmethod
    def _validate_otel_endpoint(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                f"OTEL_EXPORTER_OTLP_ENDPOINT must be an absolute http or https URL, got {value!r}"
            )
        return value


class McpFetchSettings:
    ALLOWED_PRIVATE_HOSTS: CsvTuple = Field(default=())
    MCP_FILE_URI_ROOT: str | None = Field(default=None)
    MCP_DOWNLOAD_TIMEOUT_SECONDS: float = Field(gt=0)
    FETCH_MAX_REDIRECT_HOPS: int = Field(ge=0)

    @field_validator("MCP_FILE_URI_ROOT")
    @classmethod
    def _validate_file_uri_root(cls, value: str | None) -> str | None:
        if value is not None and not Path(value).is_absolute():
            raise ValueError(f"MCP_FILE_URI_ROOT must be an absolute path, got {value!r}")
        return value

    def fetch_policy(self) -> FetchPolicy:
        root = Path(self.MCP_FILE_URI_ROOT) if self.MCP_FILE_URI_ROOT is not None else None
        return FetchPolicy(
            allowed_hosts=tuple(self.ALLOWED_PRIVATE_HOSTS),
            file_root=root,
            max_redirect_hops=self.FETCH_MAX_REDIRECT_HOPS,
        )
