from typing import Protocol, runtime_checkable


@runtime_checkable
class BaseStrategy(Protocol):
    async def extract(self, url: str) -> str:
        """
        Extracts text content from the given URL.
        Returns empty string on failure or no content.
        """
        ...

    async def get_html(self, url: str) -> str:
        """
        Returns raw HTML from the given URL without text post-processing.
        Returns empty string on failure.
        """
        ...
