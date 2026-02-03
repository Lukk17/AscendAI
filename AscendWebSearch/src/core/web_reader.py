import logging
import httpx
import trafilatura
from playwright.async_api import async_playwright
from typing import Optional

logger = logging.getLogger(__name__)

class WebReader:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    async def read(self, url: str) -> str:
        """
        Extract text from a URL.
        Strategy:
        1. Try HTTP GET + Trafilatura.
        2. If failed (403, 429) or empty content -> Try Playwright.
        """
        logger.info(f"Reading URL: {url}")
        
        # 1. Try Fast Path (HTTP + Trafilatura)
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=self.headers) as client:
                response = await client.get(url)
                
            if response.status_code in [403, 429]:
                logger.warning(f"HTTP {response.status_code} blocked. Switching to Playwright.")
                return await self._read_with_playwright(url)
            
            response.raise_for_status()
            html = response.text
            
            text = trafilatura.extract(html, include_links=True, include_images=False, include_tables=False)
            
            if self._is_valid_content(text):
                return text
            
            logger.info("Trafilatura extracted insufficient content. Switching to Playwright.")
            return await self._read_with_playwright(url)

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning(f"HTTP Request failed: {e}. Switching to Playwright.")
            return await self._read_with_playwright(url)
        except Exception as e:
            logger.error(f"Unexpected error in fast path: {e}. Switching to Playwright.")
            return await self._read_with_playwright(url)

    async def _read_with_playwright(self, url: str) -> str:
        """
        Render page with Playwright and extract content.
        """
        logger.info(f"Rendering with Playwright: {url}")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                # Create context with defined user agent and viewport
                context = await browser.new_context(
                    user_agent=self.headers["User-Agent"],
                    viewport={"width": 1280, "height": 720}
                )
                page = await context.new_page()
                
                # Navigate and wait for content
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    # wait a bit for JS to render if needed, or wait for specific selector?
                    # simple wait for now
                    await page.wait_for_timeout(2000) 
                except Exception as e:
                    logger.error(f"Playwright navigation failed: {e}")
                    await browser.close()
                    return f"Error reading page: {e}"

                content = await page.content()
                await browser.close()
                
                # Extract using trafilatura on rendered HTML
                text = trafilatura.extract(content, include_links=True)
                
                if not text:
                    return ""
                return text
                
        except Exception as e:
            logger.error(f"Playwright error: {e}")
            return f"Error rendering page: {e}"

    def _is_valid_content(self, text: Optional[str]) -> bool:
        """
        Check if extracted text is valid/sufficient.
        Criteria: Not None, length > threshold, not just cookie warning.
        """
        if not text:
            return False
        if len(text) < 200: # Arbitrary threshold for "empty" page
            return False
        # simple heuristic
        if "enable javascript" in text.lower():
            return False
        return True
