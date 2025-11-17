import colorlog
import logging
import re

class CenteredLevelFormatter(colorlog.ColoredFormatter):
    def format(self, record):
        # Let the parent class handle the initial formatting and coloring
        s = super().format(record)

        # This regex looks for " - [LEVEL] - " and captures the level part.
        match = re.search(r'(- )(\w+)( -)', s)
        if match:
            level_text = match.group(2)
            # Center the original level text and replace it in the formatted string
            centered_level = level_text.center(8)
            s = s[:match.start(2)] + centered_level + s[match.end(2):]
        return s

def setup_logging():
    """Configure application-wide logging with colors."""

    custom_log_colors = {
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red',
    }

    log_format = (
        '%(log_color)s[AudioScribe] %(asctime)s - %(levelname)s - %(module)-18s%(reset)s >> '
        '%(log_color)s%(message)s'
    )

    app_formatter = CenteredLevelFormatter(
        log_format,
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors=custom_log_colors
    )

    handler = colorlog.StreamHandler()
    handler.setFormatter(app_formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        force=True
    )

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for the given module name."""
    return logging.getLogger(name)
