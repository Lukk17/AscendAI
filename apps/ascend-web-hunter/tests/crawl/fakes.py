import fnmatch
from collections.abc import AsyncIterator


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = value
        self.ttls[key] = ttl
        return True

    async def scan_iter(self, match: str | None = None) -> AsyncIterator[str]:
        for key in list(self.store.keys()):
            if match is None or fnmatch.fnmatchcase(key, match):
                yield key
