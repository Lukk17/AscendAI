from ascend_python_common.rate_limit import build_limiter
from slowapi import Limiter

from src.config.config import settings

limiter: Limiter = build_limiter(settings.RATE_LIMIT_DEFAULT, settings.REDIS_URL, "ascend-audio-scribe")
