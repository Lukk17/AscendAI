"""Pasting on the NoVNC page types the viewer's clipboard text on the remote display.

Real Chromium, real paste events, a stub `UI` module in place of noVNC's `app/ui.js`
and a keyboard stub that does what `core/input/keyboard.js` does: swallow every key.
Proves what the page sends to `rfb.sendKey`, and that no clipboard text is sent. The rest
of the path (x11vnc, the X display, the human window) needs the running container.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Page, Route, async_playwright

_SCRIPT = Path(__file__).resolve().parents[2] / "novnc" / "paste-clipboard.js"
_PAGE_URL = "http://localhost/vnc.html"
_TEXT = "Line one\nline two, 100% exact"
_POLISH_TEXT = "zażółć Ąę Test 123"
_NON_LATIN1_KEYSYMS = {"ż": 0x1BF, "ł": 0x1B3, "ć": 0x1E6, "Ą": 0x1A1, "ę": 0x1EA}
_CONTROL_KEYSYMS = {"\n": 0xFF0D, "\t": 0xFF09}

_CTRL_DOWN = [0xFFE3, "ControlLeft", True]
_CTRL_UP = [0xFFE3, "ControlLeft", False]
_RIGHT_CTRL_DOWN = [0xFFE4, "ControlRight", True]
_RIGHT_CTRL_UP = [0xFFE4, "ControlRight", False]
_ALT_UP = [0xFFE9, "MetaLeft", False]
_SUPER_UP = [0xFFEB, "MetaRight", False]
_META_MODIFIER = 4
_MAX_PASTED_CHARACTERS = 10000

_UI_STUB = """
window.sent = {text: [], keys: [], status: []};
const UI = {showStatus(text, statusType) { window.sent.status.push([text, statusType]); }};
if (!window.disconnected) {
  UI.rfb = {
    clipboardPasteFrom(text) { window.sent.text.push(text); },
    sendKey(keysym, code, down) {
      window.sent.keys.push([keysym, code, down === undefined ? "press" : down]);
    },
  };
}
export default UI;
"""

_KEYSYMDEF_STUB = (
    "const table = {0x17c: 0x1bf, 0x142: 0x1b3, 0x107: 0x1e6, 0x104: 0x1a1, 0x119: 0x1ea};\n"
    "export default { lookup: (u) => (u >= 0x20 && u <= 0xff) ? u : (table[u] ?? (0x01000000 | u)) };\n"
)

_HTML = """<!DOCTYPE html><html><body>
<canvas id="screen" tabindex="-1" width="300" height="200"></canvas>
<textarea id="noVNC_keyboardinput">____</textarea>
<textarea id="noVNC_clipboard_text"></textarea>
<input id="noVNC_password_input" type="password">
<script type="module" src="app/paste-clipboard.js"></script>
<script type="module">
import UI from "./app/ui.js";
window.keyboardSaw = [];
const controlKeysym = {ControlLeft: 0xffe3, ControlRight: 0xffe4};
for (const id of ["screen", "noVNC_keyboardinput"]) {
  const target = document.getElementById(id);
  target.addEventListener("keydown", (e) => {
    if (e.key === "Unidentified") return;
    e.stopPropagation();
    e.preventDefault();
    window.keyboardSaw.push(e.key);
    if (e.key === "Control") UI.rfb?.sendKey(controlKeysym[e.code], e.code, true);
  });
  target.addEventListener("keyup", (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (e.key === "Control") UI.rfb?.sendKey(controlKeysym[e.code], e.code, false);
  });
}
document.getElementById("noVNC_keyboardinput").addEventListener("input", (e) => {
  UI.rfb?.sendKey(e.target.value, "typed");
});
window.ready = true;
</script>
</body></html>"""


_HASHED_PAGE_PATH = "/hashed.html"
_HASHED_HTML = _HTML.replace('src="app/paste-clipboard.js"', 'src="app/paste-clipboard.js?v=abc123def456"')


async def _serve(route: Route) -> None:
    url = urlsplit(route.request.url).path
    if url.endswith("/app/ui.js"):
        await route.fulfill(body=_UI_STUB, content_type="text/javascript")
    elif url.endswith("/core/input/keysymdef.js"):
        await route.fulfill(body=_KEYSYMDEF_STUB, content_type="text/javascript")
    elif url.endswith("/app/paste-clipboard.js"):
        await route.fulfill(body=_SCRIPT.read_text(encoding="utf-8"), content_type="text/javascript")
    elif url == _HASHED_PAGE_PATH:
        await route.fulfill(body=_HASHED_HTML, content_type="text/html")
    else:
        await route.fulfill(body=_HTML, content_type="text/html")


@pytest.fixture
async def browser_context() -> AsyncIterator[Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            await context.route("http://localhost/**", _serve)
            yield context
        finally:
            await browser.close()


def _typed(text: str) -> list[list[Any]]:
    keysyms = {**_NON_LATIN1_KEYSYMS, **_CONTROL_KEYSYMS}
    return [[keysyms.get(char, ord(char)), "", "press"] for char in text]


async def _open(
    context: Any, init_script: str | None = None, clipboard_text: str = _TEXT, page_url: str = _PAGE_URL
) -> tuple[Page, list[str]]:
    page = await context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    if init_script:
        await page.add_init_script(init_script)
    await page.goto(page_url)
    await page.wait_for_function("window.ready === true")
    await page.evaluate("text => navigator.clipboard.writeText(text)", clipboard_text)
    return page, errors


async def _press_ctrl_v(page: Page) -> None:
    await page.keyboard.down("Control")
    await page.keyboard.press("v")
    await page.keyboard.up("Control")


async def _browser_paste(page: Page, *, key: str, code: str, modifiers: int) -> None:
    session = await page.context.new_cdp_session(page)
    event = {"key": key, "code": code, "modifiers": modifiers}
    await session.send("Input.dispatchKeyEvent", {"type": "keyDown", "commands": ["paste"], **event})
    await session.send("Input.dispatchKeyEvent", {"type": "keyUp", **event})


async def _sent(page: Page) -> dict[str, list[Any]]:
    sent: dict[str, list[Any]] = await page.evaluate("window.sent")
    return sent


async def test_right_ctrl_v_on_the_screen_releases_and_restores_right_control(browser_context: Any) -> None:
    # given
    page, errors = await _open(browser_context)
    await page.focus("#screen")

    # when
    await page.keyboard.down("ControlRight")
    await page.keyboard.press("v")
    await page.keyboard.up("ControlRight")

    # then
    sent = await _sent(page)
    assert sent["keys"] == [
        _RIGHT_CTRL_DOWN,
        _RIGHT_CTRL_UP,
        *_typed(_TEXT),
        _RIGHT_CTRL_DOWN,
        _RIGHT_CTRL_UP,
    ]
    assert errors == []


async def test_paste_above_the_limit_is_refused_before_any_key_is_sent(browser_context: Any) -> None:
    # given
    page, errors = await _open(browser_context, clipboard_text="x" * (_MAX_PASTED_CHARACTERS + 1))
    await page.focus("#screen")

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent["keys"] == [_CTRL_DOWN, _CTRL_UP]
    assert [status_type for _, status_type in sent["status"]] == ["warn"]
    assert str(_MAX_PASTED_CHARACTERS) in sent["status"][0][0]
    assert errors == []


async def test_paste_of_exactly_the_limit_is_typed(browser_context: Any) -> None:
    # given
    text = "x" * _MAX_PASTED_CHARACTERS
    page, errors = await _open(browser_context, clipboard_text=text)
    await page.focus("#screen")

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent["keys"] == [_CTRL_DOWN, _CTRL_UP, *_typed(text), _CTRL_DOWN, _CTRL_UP]
    assert sent["status"] == []
    assert errors == []


async def test_ctrl_v_on_the_screen_types_the_text_with_control_released(browser_context: Any) -> None:
    # given
    page, errors = await _open(browser_context)
    await page.focus("#screen")

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent["text"] == []
    assert sent["keys"] == [_CTRL_DOWN, _CTRL_UP, *_typed(_TEXT), _CTRL_DOWN, _CTRL_UP]
    assert "v" not in await page.evaluate("window.keyboardSaw")
    assert errors == []


async def test_a_query_on_the_script_address_keeps_one_ui_module_and_paste_works(
    browser_context: Any,
) -> None:
    # given
    requested: list[str] = []
    browser_context.on("request", lambda request: requested.append(request.url))
    page, errors = await _open(browser_context, page_url=f"http://localhost{_HASHED_PAGE_PATH}")
    await page.focus("#screen")

    # when
    await _press_ctrl_v(page)

    # then
    assert [url for url in requested if "ui.js" in url] == ["http://localhost/app/ui.js"]
    assert (await _sent(page))["keys"] == [_CTRL_DOWN, _CTRL_UP, *_typed(_TEXT), _CTRL_DOWN, _CTRL_UP]
    assert errors == []


async def test_ctrl_v_with_polish_letters_types_their_keysyms(browser_context: Any) -> None:
    # given
    page, errors = await _open(browser_context, clipboard_text=_POLISH_TEXT)
    await page.focus("#screen")

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent["text"] == []
    assert sent["keys"] == [_CTRL_DOWN, _CTRL_UP, *_typed(_POLISH_TEXT), _CTRL_DOWN, _CTRL_UP]
    assert errors == []


async def test_windows_line_endings_become_one_return(browser_context: Any) -> None:
    # given
    page, errors = await _open(browser_context, clipboard_text="one\r\ntwo\tthree")
    await page.focus("#screen")

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent["keys"] == [_CTRL_DOWN, _CTRL_UP, *_typed("one\ntwo\tthree"), _CTRL_DOWN, _CTRL_UP]
    assert errors == []


async def test_ctrl_v_in_the_keyboard_box_types_on_the_remote_and_not_in_the_box(
    browser_context: Any,
) -> None:
    # given
    page, errors = await _open(browser_context)
    await page.focus("#noVNC_keyboardinput")

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent["text"] == []
    assert sent["keys"] == [_CTRL_DOWN, _CTRL_UP, *_typed(_TEXT), _CTRL_DOWN, _CTRL_UP]
    assert await page.input_value("#noVNC_keyboardinput") == "____"
    assert errors == []


async def test_a_paste_without_a_shortcut_in_the_keyboard_box_types_the_text(
    browser_context: Any,
) -> None:
    # given
    page, errors = await _open(browser_context)
    await page.focus("#noVNC_keyboardinput")

    # when
    await _browser_paste(page, key="Unidentified", code="", modifiers=0)

    # then
    sent = await _sent(page)
    assert sent["text"] == []
    assert sent["keys"] == _typed(_TEXT)
    assert await page.input_value("#noVNC_keyboardinput") == "____"
    assert errors == []


async def test_ctrl_v_with_the_screen_not_focused_types_the_text(browser_context: Any) -> None:
    # given
    page, errors = await _open(browser_context)
    await page.evaluate("document.activeElement.blur()")

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent["text"] == []
    assert sent["keys"] == _typed(_TEXT)
    assert errors == []


async def test_cmd_v_on_a_mac_releases_the_held_cmd_before_typing(browser_context: Any) -> None:
    # given
    page, errors = await _open(
        browser_context, "Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'})"
    )
    await page.focus("#screen")

    # when
    await page.keyboard.down("Meta")
    await _browser_paste(page, key="v", code="KeyV", modifiers=_META_MODIFIER)
    await page.keyboard.up("Meta")

    # then
    sent = await _sent(page)
    assert sent["text"] == []
    assert sent["keys"] == [_ALT_UP, _SUPER_UP, *_typed(_TEXT)]
    assert "v" not in await page.evaluate("window.keyboardSaw")
    assert errors == []


async def test_ctrl_v_on_a_mac_stays_an_ordinary_remote_shortcut(browser_context: Any) -> None:
    # given
    page, errors = await _open(
        browser_context, "Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'})"
    )
    await page.focus("#screen")

    # when
    await page.keyboard.down("Control")
    await page.keyboard.press("v")
    await page.keyboard.up("Control")

    # then
    assert "v" in await page.evaluate("window.keyboardSaw")
    assert (await _sent(page))["text"] == []
    assert errors == []


async def test_without_a_connection_nothing_is_sent_and_nothing_throws(browser_context: Any) -> None:
    # given
    page, errors = await _open(browser_context, "window.disconnected = true")
    await page.focus("#screen")

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent == {"text": [], "keys": [], "status": []}
    assert "v" in await page.evaluate("window.keyboardSaw")
    assert errors == []


@pytest.mark.parametrize(
    "field",
    [
        pytest.param("#noVNC_clipboard_text", id="clipboard-side-panel"),
        pytest.param("#noVNC_password_input", id="vnc-password-dialog"),
    ],
)
async def test_a_paste_into_a_form_field_stays_in_that_field(browser_context: Any, field: str) -> None:
    # given
    page, errors = await _open(browser_context)
    await page.focus(field)

    # when
    await _press_ctrl_v(page)

    # then
    sent = await _sent(page)
    assert sent == {"text": [], "keys": [], "status": []}
    expected = _TEXT if field == "#noVNC_clipboard_text" else _TEXT.replace("\n", " ")
    assert await page.input_value(field) == expected
    assert errors == []


async def test_altgr_v_is_left_to_novnc(browser_context: Any) -> None:
    # given
    page, errors = await _open(browser_context)
    await page.focus("#screen")

    # when
    await page.keyboard.down("Control")
    await page.keyboard.down("Alt")
    await page.keyboard.press("v")
    await page.keyboard.up("Alt")
    await page.keyboard.up("Control")

    # then
    assert "v" in await page.evaluate("window.keyboardSaw")
    assert (await _sent(page))["text"] == []
    assert errors == []
