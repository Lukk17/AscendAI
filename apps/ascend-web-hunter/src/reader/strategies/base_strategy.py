from collections.abc import Mapping
from typing import Protocol, Self, runtime_checkable


class FetchedHtml(str):
    """HTML of one read with the ``ETag`` and ``Last-Modified`` of the final answer that carried it."""

    etag: str | None
    last_modified: str | None

    def __new__(cls, html: str, headers: Mapping[str, str]) -> Self:
        page = super().__new__(cls, html)
        page.etag = headers.get("etag")
        page.last_modified = headers.get("last-modified")

        return page


def validators_of(page: str) -> tuple[str | None, str | None]:
    """The ``ETag`` and ``Last-Modified`` the final answer of *page* carried, None for each one it did not."""
    if isinstance(page, FetchedHtml):
        return page.etag, page.last_modified

    return None, None


@runtime_checkable
class BaseStrategy(Protocol):
    # noinspection PyAsyncCall
    async def extract(self, url: str) -> str:
        """
        Extracts text content from the given URL.
        Returns empty string on failure or no content.
        Protocol stub: implementations override; the `...` body is the documented
        Python idiom for Protocol signatures, not dead code.
        """
        ...

    # noinspection PyAsyncCall
    async def get_html(self, url: str) -> FetchedHtml | str:
        """
        Returns raw HTML from the given URL without text post-processing.
        Returns empty string on failure.
        Protocol stub: see extract().
        """
        ...
