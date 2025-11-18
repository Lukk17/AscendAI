import logging

from src.config.logging_config import get_logger, setup_logging


def test_get_logger():
    logger_name = "my_test_logger"
    logger = get_logger(logger_name)
    assert isinstance(logger, logging.Logger)
    assert logger.name == logger_name


def test_setup_logging():
    try:
        setup_logging()
    except Exception as e:
        assert False, f"setup_logging raised an exception: {e}"
