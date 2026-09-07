import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from adblockparser import AdblockRules

from src.config.config import settings

logger = logging.getLogger(__name__)


class BlocklistValidationError(Exception):
    """Raised when a freshly downloaded blocklist contains no usable rules."""


class BlocklistRefreshThrottledError(Exception):
    """Raised when refresh() is called again before the configured cooldown has elapsed."""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Blocklist refresh throttled; retry after {retry_after_seconds:.0f}s")


@dataclass(frozen=True)
class BlocklistState:
    rule_count: int
    loaded_at: datetime


class BlocklistLoader:
    """Loads the ad/annoyance blocklist from the single file vendored into the
    container image, and refreshes it on demand from settings.BLOCKLIST_URL.

    load_rules() and refresh() both read/write settings.BLOCKLIST_PATH -- the
    exact file the Dockerfile bakes into the image via `COPY src/ src/` -- so a
    successful refresh always lands where the next load, and the next process
    restart, will look for it.
    """

    def __init__(self, blocklist_path: str | None = None) -> None:
        self.blocklist_path = Path(blocklist_path) if blocklist_path else Path(settings.BLOCKLIST_PATH)
        self._refresh_lock = asyncio.Lock()
        self._last_refresh_attempt: float | None = None
        self._state: BlocklistState | None = None

    @property
    def state(self) -> BlocklistState | None:
        return self._state

    def load_rules(self) -> AdblockRules:
        """Load the vendored blocklist from disk. Never downloads.

        The file ships inside the container image, so its absence or corruption
        is a packaging defect rather than a state to recover from at runtime:
        both raise loudly instead of silently starting with an empty ruleset,
        which would let every URL through unfiltered.
        """
        if not self.blocklist_path.exists():
            raise FileNotFoundError(
                f"Blocklist file not found at {self.blocklist_path}. It ships inside the container "
                "image (see the Dockerfile's `COPY src/ src/`); a missing file means the image was "
                "built without it, not a state to fall back from at runtime."
            )
        try:
            rules, count = self._parse_file(self.blocklist_path)
        except Exception as e:
            raise RuntimeError(
                f"Blocklist file at {self.blocklist_path} exists but could not be read or parsed"
            ) from e

        self._state = BlocklistState(rule_count=count, loaded_at=datetime.now(UTC))
        logger.info(f"Loaded {count} blocklist rules from {self.blocklist_path}.")

        return rules

    async def refresh(self) -> tuple[AdblockRules, BlocklistState]:
        """Download, validate, and atomically swap the on-disk and in-memory blocklist.

        A failure at any step -- throttled, network, empty result, unparsable
        content -- leaves both the file on disk and the previously loaded rules
        untouched, so an outside failure never degrades the running service.
        Concurrent calls are serialised on an asyncio.Lock; only one attempt
        runs the network request at a time.

        Raises:
            BlocklistRefreshThrottledError: called again before the configured cooldown elapsed.
            httpx.HTTPError: the download itself failed.
            BlocklistValidationError: the download succeeded but yielded no usable rules.
        """
        async with self._refresh_lock:
            self._raise_if_too_soon()
            self._last_refresh_attempt = time.monotonic()

            logger.info(f"Refreshing blocklist from {settings.BLOCKLIST_URL}...")
            async with httpx.AsyncClient(timeout=settings.DEFAULT_TIMEOUT) as client:
                response = await client.get(settings.BLOCKLIST_URL, follow_redirects=True)
                response.raise_for_status()
                content = response.content

            raw_rules = self._extract_rule_lines(content.decode("utf-8", errors="ignore"))
            if not raw_rules:
                raise BlocklistValidationError(
                    f"Downloaded blocklist from {settings.BLOCKLIST_URL} contained no usable rules; "
                    "the previously loaded list remains active."
                )
            rules = AdblockRules(raw_rules)

            self._atomic_write(content)
            state = BlocklistState(rule_count=len(raw_rules), loaded_at=datetime.now(UTC))
            self._state = state
            logger.info(f"Blocklist refreshed: {len(raw_rules)} rules now active.")

            return rules, state

    def _raise_if_too_soon(self) -> None:
        if self._last_refresh_attempt is None:
            return
        elapsed = time.monotonic() - self._last_refresh_attempt
        remaining = settings.BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            raise BlocklistRefreshThrottledError(remaining)

    def _atomic_write(self, content: bytes) -> None:
        tmp_path = self.blocklist_path.with_suffix(".tmp")
        tmp_path.write_bytes(content)
        tmp_path.replace(self.blocklist_path)

    @staticmethod
    def _extract_rule_lines(text: str) -> list[str]:
        return [
            line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("!")
        ]

    def _parse_file(self, path: Path) -> tuple[AdblockRules, int]:
        with path.open(encoding="utf-8", errors="ignore") as f:
            raw_rules = self._extract_rule_lines(f.read())

        return AdblockRules(raw_rules), len(raw_rules)


blocklist_loader = BlocklistLoader()
