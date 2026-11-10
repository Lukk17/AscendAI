"""Readers and cache keys the unit and integration purge tests share."""

import asyncio

from src.reader.web_reader import ReadCacheKey, WebReader, _cache_key

_GONE_POLLS = 300
_GONE_POLL_SECONDS = 0.01


def seeded_reader(entries: dict[ReadCacheKey, str]) -> WebReader:
    reader = WebReader()
    for key, content in entries.items():
        reader._memory_cache[key] = ({"content": content, "status": "success", "mode": "t"}, 9999999999.0)
    return reader


def domain_key(domain: str, path: str) -> ReadCacheKey:
    return _cache_key(f"https://{domain}/{path}", False, False, None, "text")


async def wait_until_gone(reader: WebReader, key: ReadCacheKey) -> None:
    for _ in range(_GONE_POLLS):
        if key not in reader._memory_cache:
            return
        await asyncio.sleep(_GONE_POLL_SECONDS)
