from typing import Protocol, runtime_checkable


@runtime_checkable
class BaseStrategy(Protocol):
    async def extract(self, url: str) -> str:
        """
        Extracts content from the given URL.
        Returns empty string on failure or no content.
        Should raise exceptions if critical, but generally return valid str.
        """
        ...
