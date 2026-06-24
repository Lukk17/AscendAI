"""Seed authenticated Playwright storage_state into the AscendWebSearch session store.

For each configured login service, scripts a login, captures the resulting
storage_state, and persists it under the 'e2e' profile via the service's own
CookieManager so the Bruno test runs can replay the session.

Credentials are hardcoded per service. saucedemo's are its public demo credentials
(shown on its own login page) — not secrets. A future service that needs real
secret credentials should read them from the environment, never commit them here.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LoginService:
    name: str
    username: str
    password: str
    login_url: str
    secure_url: str
    username_selector: str
    pw_selector: str
    submit_selector: str


SERVICES: tuple[LoginService, ...] = (
    LoginService(
        name="saucedemo",
        username="standard_user",
        password=os.environ.get("SAUCEDEMO_PASSWORD", "secret_sauce"),
        login_url="https://www.saucedemo.com/",
        secure_url="https://www.saucedemo.com/inventory.html",
        username_selector="#user-name",
        pw_selector="#password",
        submit_selector="#login-button",
    ),
)


async def _seed_service(service: LoginService) -> None:
    from playwright.async_api import async_playwright

    from src.reader.cloudflare.cookie_manager import cookie_manager

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(service.login_url)
        await page.fill(service.username_selector, service.username)
        await page.fill(service.pw_selector, service.password)
        await page.click(service.submit_selector)
        await page.wait_for_load_state("networkidle")
        storage_state: dict[str, Any] = await context.storage_state()
        user_agent: str = await page.evaluate("() => navigator.userAgent")
        await browser.close()

    await cookie_manager.save_storage_state(
        url=service.secure_url,
        storage_state=storage_state,
        user_agent=user_agent,
        profile="e2e",
    )
    sys.stdout.write(f"[seed] {service.name}: session seeded under profile 'e2e'.\n")


async def _run() -> None:
    for service in SERVICES:
        await _seed_service(service)


if __name__ == "__main__":
    asyncio.run(_run())
