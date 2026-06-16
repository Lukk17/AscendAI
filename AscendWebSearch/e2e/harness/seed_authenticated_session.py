"""Seed an authenticated Playwright storage_state into the AscendWebSearch session store.

Reads login credentials from environment variables (or AscendWebSearch/e2e/.env.local),
performs a scripted login via Playwright, captures the resulting storage_state, and
persists it under the 'e2e' profile using the service's own CookieManager so that
subsequent Bruno test runs can replay the session.

Required environment variables:
    E2E_LOGIN_URL                 — the URL of the login page
    E2E_LOGIN_USER                — username / email to enter
    E2E_LOGIN_PASS                — password to enter
    E2E_LOGIN_SECURE_URL          — URL that is only accessible when authenticated

Optional environment variables (selectors default to saucedemo's DOM):
    E2E_LOGIN_USERNAME_SELECTOR   — CSS selector for the username input (default: #user-name)
    E2E_LOGIN_PASSWORD_SELECTOR   — CSS selector for the password input (default: #password)
    E2E_LOGIN_SUBMIT_SELECTOR     — CSS selector for the submit button (default: #login-button)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any


def _load_env_local() -> None:
    """Parse .env.local from the e2e directory (one level up from this harness) into os.environ.

    Only sets variables that are not already present in the environment — existing
    values (e.g. from a CI secret store) take precedence.
    """
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
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


def _require_env(name: str) -> str:
    """Return the value of a required environment variable or exit with a clear message."""
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(
            f"[seed_authenticated_session] Missing required env var: {name}\n"
            "Set it in AscendWebSearch/e2e/.env.local or export it before running this script.\n"
            "Skipping authenticated section.\n"
        )
        sys.exit(1)
    return value


async def _run() -> None:
    from playwright.async_api import async_playwright

    from src.reader.cloudflare.cookie_manager import cookie_manager

    login_url = _require_env("E2E_LOGIN_URL")
    login_user = _require_env("E2E_LOGIN_USER")
    login_pass = _require_env("E2E_LOGIN_PASS")
    secure_url = _require_env("E2E_LOGIN_SECURE_URL")

    username_selector = os.environ.get("E2E_LOGIN_USERNAME_SELECTOR", "#user-name")
    password_selector = os.environ.get("E2E_LOGIN_PASSWORD_SELECTOR", "#password")
    submit_selector = os.environ.get("E2E_LOGIN_SUBMIT_SELECTOR", "#login-button")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(login_url)
        await page.fill(username_selector, login_user)
        await page.fill(password_selector, login_pass)
        await page.click(submit_selector)
        await page.wait_for_load_state("networkidle")

        storage_state: dict[str, Any] = await context.storage_state()
        user_agent: str = await page.evaluate("() => navigator.userAgent")

        await browser.close()

    await cookie_manager.save_storage_state(
        url=secure_url,
        storage_state=storage_state,
        user_agent=user_agent,
        profile="e2e",
    )

    sys.stdout.write(
        f"[seed_authenticated_session] Session seeded for {secure_url!r} under profile 'e2e'.\n"
    )


if __name__ == "__main__":
    _load_env_local()
    asyncio.run(_run())
