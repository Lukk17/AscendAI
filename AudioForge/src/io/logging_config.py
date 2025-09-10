import logging
import colorlog


def setup_logging():
    """Configure application-wide logging with colors."""
    app_formatter = colorlog.ColoredFormatter(
        '%(white)s[AudioForge] %(asctime)s - %(levelname)s - %(module)s%(reset)s\n%(log_color)s%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',      # Message color
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold_red',
        },
        secondary_log_colors={
            'white': {
                'DEBUG': 'white',
                'INFO': 'white',    # Header always white
                'WARNING': 'white',
                'ERROR': 'white',
                'CRITICAL': 'white',
            }
        }
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