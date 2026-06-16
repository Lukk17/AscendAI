"""Seed authenticated Playwright storage_state into the AscendWebSearch session store.

For each configured login-walled service whose credentials are present in the
environment (or AscendWebSearch/e2e/.env.local), this scripts a login, captures the
resulting storage_state, and persists it under the 'e2e' profile via the service's
own CookieManager so the Bruno test runs can replay the session.

Only credentials live in the environment — one USER/PASS pair per service. Login
URLs, secure URLs, and DOM selectors are hardcoded below so the test is fixed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LoginService:
    name: str
    user_env: str
    pass_env: str
    login_url: str
    secure_url: str
    username_selector: str
    password_selector: str
    submit_selector: str


SERVICES: tuple[LoginService, ...] = (
    LoginService(
        name="saucedemo",
        user_env="SAUCEDEMO_USER",
        pass_env="SAUCEDEMO_PASS",
        login_url="https://www.saucedemo.com/",
        secure_url="https://www.saucedemo.com/inventory.html",
        username_selector="#user-name",
        password_selector="#password",
        submit_selector="#login-button",
    ),
)


def _load_env_local() -> None:
    e2e_dir = Path(__file__).resolve().parents[1]
    env_local = e2e_dir / ".env.local"
    if not env_local.exists():
        return

    with env_local.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


async def _seed_service(service: LoginService) -> bool:
    from playwright.async_api import async_playwright

    from src.reader.cloudflare.cookie_manager import cookie_manager

    user = os.environ.get(service.user_env)
    password = os.environ.get(service.pass_env)
    if not user or not password:
        sys.stdout.write(
            f"[seed] {service.name}: no credentials "
            f"({service.user_env}/{service.pass_env}) — skipped.\n"
        )
        return False

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(service.login_url)
        await page.fill(service.username_selector, user)
        await page.fill(service.password_selector, password)
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
    return True


async def _run() -> None:
    seeded = 0
    for service in SERVICES:
        if await _seed_service(service):
            seeded += 1

    if seeded == 0:
        sys.stdout.write(
            "[seed] No services seeded — set credentials in AscendWebSearch/e2e/.env.local.\n"
        )


if __name__ == "__main__":
    _load_env_local()
    asyncio.run(_run())
