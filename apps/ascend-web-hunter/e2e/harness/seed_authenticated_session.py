"""Seed an authenticated Playwright storage_state through the session import endpoint.

For each configured login service, scripts a login, captures the resulting
storage_state, and sends it to ``POST {WEB_HUNTER_BASE_URL}/api/v2/web/session/import``
under the 'e2e' profile, so the Bruno test runs can replay the session.

Credentials are hardcoded per service. saucedemo's are its public demo credentials
(shown on its own login page) - not secrets. A future service that needs real
secret credentials should read them from the environment, never commit them here.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx

WEB_HUNTER_BASE_URL = os.environ.get("WEB_HUNTER_BASE_URL", "http://localhost:7021")


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

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(service.login_url)
        await page.fill(service.username_selector, service.username)
        await page.fill(service.pw_selector, service.password)
        await page.click(service.submit_selector)
        await page.wait_for_load_state("networkidle")
        storage_state: Any = await context.storage_state()
        user_agent: str = await page.evaluate("() => navigator.userAgent")
        await browser.close()

    async with httpx.AsyncClient(base_url=WEB_HUNTER_BASE_URL, timeout=30) as client:
        resp = await client.post(
            "/api/v2/web/session/import",
            json={
                "url": service.secure_url,
                "profile": "e2e",
                "storage_state": storage_state,
                "user_agent": user_agent,
            },
        )
    if resp.status_code != 200:
        sys.stderr.write(
            f"[seed] {service.name}: import failed with {resp.status_code}: {resp.text}\n"
        )
        raise SystemExit(1)
    sys.stdout.write(f"[seed] {service.name}: session seeded under profile 'e2e'.\n")


async def _run() -> None:
    for service in SERVICES:
        await _seed_service(service)


if __name__ == "__main__":
    asyncio.run(_run())
