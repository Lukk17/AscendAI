"""The NoVNC window finds a password input that sits inside an open shadow root.

Real Chromium, shaped like the old.reddit.com login page measured on 2026-11-07:
the login form is drawn by a web component, so the rendered markup the window
reads carries no password input and only Playwright's locator, which pierces
open shadow roots, sees it.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from playwright.async_api import async_playwright

from src.reader.cloudflare.challenge_detector import has_password_input
from src.reader.strategies.novnc_strategy import _has_password_input

_SHADOW_LOGIN_PAGE = """<html><head><title>Welcome to Example</title></head><body>
<example-login></example-login>
<script>
customElements.define("example-login", class extends HTMLElement {
  connectedCallback() {
    const form = document.createElement("form");
    for (const [name, type] of [["user", "text"], ["password", "password"]]) {
      const field = document.createElement("input");
      field.name = name;
      field.type = type;
      form.append(field);
    }
    this.attachShadow({mode: "open"}).append(form);
  }
});
</script>
</body></html>"""

_SHADOW_TEXT_PAGE = _SHADOW_LOGIN_PAGE.replace('["password", "password"]', '["query", "search"]')


@pytest.fixture
async def page() -> AsyncIterator[Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            yield await browser.new_page()
        finally:
            await browser.close()


async def test_a_password_input_inside_an_open_shadow_root_is_found(page: Any) -> None:
    # given
    await page.set_content(_SHADOW_LOGIN_PAGE)
    page_content = await page.content()

    # when
    found = await _has_password_input(page)

    # then
    assert has_password_input(page_content) is False
    assert found is True


async def test_a_shadow_root_without_a_password_input_is_no_login_page(page: Any) -> None:
    # given
    await page.set_content(_SHADOW_TEXT_PAGE)

    # when
    found = await _has_password_input(page)

    # then
    assert found is False


@pytest.mark.parametrize(
    "markup",
    [
        pytest.param("<form hidden><input type='password' name='password'></form>", id="hidden-form"),
        pytest.param("<input type='password' name='password' style='display:none'>", id="display-none"),
        pytest.param("<noscript><input type='password' name='password'></noscript>", id="noscript"),
        pytest.param("<template><input type='password' name='password'></template>", id="template"),
        pytest.param("<script>const f = \"<input type='password'>\";</script>", id="script-text"),
    ],
)
async def test_a_password_input_nobody_can_see_is_no_login_page(page: Any, markup: str) -> None:
    # given
    await page.set_content(
        f"<html><head><title>Home</title></head><body>{markup}<p>Welcome back</p></body></html>"
    )

    # when
    found = await _has_password_input(page)

    # then
    assert found is False
