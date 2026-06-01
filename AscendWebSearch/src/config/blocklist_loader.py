import logging
from pathlib import Path

import httpx
from adblockparser import AdblockRules

from src.config.config import settings

logger = logging.getLogger(__name__)


class BlocklistLoader:
    def __init__(self, assets_dir: str | None = None):
        if assets_dir:
            self.assets_dir = Path(assets_dir)
        else:
            self.assets_dir = Path(__file__).parent.parent / "assets"

        self.blocklist_path = self.assets_dir / "fanboy-annoyance.txt"
        self._ensure_assets_dir()

    def _ensure_assets_dir(self) -> None:
        if not self.assets_dir.exists():
            self.assets_dir.mkdir(parents=True, exist_ok=True)

    def load_rules(self) -> AdblockRules:
        self._download_blocklist()
        return self._parse_rules()

    def _download_blocklist(self) -> None:
        logger.info(f"Downloading blocklist from {settings.BLOCKLIST_URL}...")
        try:
            with httpx.Client() as client:
                response = client.get(settings.BLOCKLIST_URL, follow_redirects=True)
                response.raise_for_status()
                with self.blocklist_path.open("wb") as f:
                    f.write(response.content)
            logger.info("Blocklist downloaded successfully.")
        except Exception as e:
            logger.exception("Failed to download blocklist")
            raise RuntimeError(f"Critical: Could not download blocklist from {settings.BLOCKLIST_URL}") from e

    def _parse_rules(self) -> AdblockRules:
        if not self.blocklist_path.exists():
            raise FileNotFoundError(f"Blocklist file not found at {self.blocklist_path}")

        logger.info("Parsing blocklist rules...")
        try:
            with self.blocklist_path.open(encoding="utf-8", errors="ignore") as f:
                raw_rules = [line.strip() for line in f if line.strip() and not line.strip().startswith("!")]
                rules = AdblockRules(raw_rules)
            logger.info(f"Loaded {len(raw_rules)} rules.")
            return rules
        except Exception as e:
            logger.exception("Failed to parse blocklist rules")
            raise RuntimeError("Critical: Could not parse blocklist rules") from e
