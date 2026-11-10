import pytest

from src.config.config import Settings
from src.config.config import settings as service_settings
from src.main import _service_definition


def test_redis_url_default_is_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("REDIS_URL", raising=False)
    # when
    default = Settings().REDIS_URL
    # then
    assert default == "redis://127.0.0.1:6379/0"


def test_rate_limit_storage_uri_equals_redis_url() -> None:
    # given
    definition = _service_definition()
    # when
    storage_uri = definition.rate_limit_storage_uri
    # then
    assert storage_uri == service_settings.REDIS_URL
