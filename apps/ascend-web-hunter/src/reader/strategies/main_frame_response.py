"""The latest main-frame document response of one browser page."""

from playwright.async_api import Page, Response

from src.reader.strategies.base_strategy import FetchedHtml

DEFAULT_STATUS = 200


def is_main_frame_document(response: Response) -> bool:
    """True when *response* answers a navigation of a page's main frame."""
    return response.request.is_navigation_request() and response.frame.parent_frame is None


class MainFrameResponses:
    """Records the latest main-frame document response of *page* from its first navigation on."""

    def __init__(self, page: Page) -> None:
        self._latest: Response | None = None
        page.on("response", self._record)

    def _record(self, response: Response) -> None:
        if is_main_frame_document(response):
            self._latest = response

    def seed(self, response: Response | None) -> None:
        """Take the navigation's own response when no response event recorded one first."""
        if self._latest is None:
            self._latest = response

    async def status_and_headers(self) -> tuple[int, dict[str, str]]:
        """Status and all headers of the latest main-frame response, 200 and none before any."""
        if self._latest is None:
            return DEFAULT_STATUS, {}

        return self._latest.status, await self.headers()

    async def headers(self) -> dict[str, str]:
        """All headers of the latest main-frame response, none before any."""
        if self._latest is None:
            return {}

        return await self._latest.all_headers()

    async def page_html(self, content: str) -> FetchedHtml:
        """*content* with the cache validators of the latest main-frame response."""
        return FetchedHtml(content, await self.headers())
