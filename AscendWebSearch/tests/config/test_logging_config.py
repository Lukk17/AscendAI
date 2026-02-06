import logging
from unittest.mock import patch

from src.config.logging_config import setup_logging, get_uvicorn_log_config


def test_setup_logging():
    # given
    with patch("logging.basicConfig") as mock_basic_config:
        # when
        setup_logging()

        # then
        mock_basic_config.assert_called_once()
        args, kwargs = mock_basic_config.call_args
        assert kwargs["level"] == logging.INFO
        assert "handlers" in kwargs
        assert len(kwargs["handlers"]) == 1


def test_get_uvicorn_log_config():
    # given
    # when
    config = get_uvicorn_log_config()

    # then
    assert isinstance(config, dict)
    assert "version" in config
    assert config["version"] == 1
    assert "formatters" in config
