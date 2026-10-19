"""Unit tests for the wrapping cascade of `window_layout.rect_for_slot`."""

from src.config.config import settings
from src.reader.novnc.window_layout import WindowRect, rect_for_slot


def _default_rect(slot: int) -> WindowRect:
    # given
    display_size = settings.NOVNC_DISPLAY_SIZE
    window_size = (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX)
    offset = settings.NOVNC_WINDOW_CASCADE_OFFSET_PX

    # when
    return rect_for_slot(slot, display_size, window_size, offset)


def test_every_slot_through_the_cap_and_one_past_stays_inside_the_display() -> None:
    # given
    cap = settings.NOVNC_MAX_CONCURRENT_FLOWS
    display_width, display_height = (1920, 1080)

    # when / then
    for slot in range(cap + 1):
        rect = _default_rect(slot)
        assert rect.slot == slot
        assert rect.x >= 0
        assert rect.x + rect.width <= display_width
        assert rect.y >= 0
        assert rect.y + rect.height <= display_height


def test_two_different_slots_up_to_the_cap_give_two_different_positions() -> None:
    # given
    cap = settings.NOVNC_MAX_CONCURRENT_FLOWS

    # when
    positions = {(rect.x, rect.y) for rect in (_default_rect(slot) for slot in range(cap + 1))}

    # then
    assert len(positions) == cap + 1


def test_window_size_is_constant_across_slots() -> None:
    # given
    cap = settings.NOVNC_MAX_CONCURRENT_FLOWS

    # when / then
    for slot in range(cap + 1):
        rect = _default_rect(slot)
        assert rect.width == settings.NOVNC_WINDOW_WIDTH_PX
        assert rect.height == settings.NOVNC_WINDOW_HEIGHT_PX


def test_another_display_size_window_size_and_offset_are_honoured() -> None:
    # when
    first = rect_for_slot(0, "800x600", (400, 300), 25)
    third = rect_for_slot(2, "800x600", (400, 300), 25)

    # then
    assert (first.x, first.y, first.width, first.height) == (0, 0, 400, 300)
    assert (third.x, third.y, third.width, third.height) == (50, 50, 400, 300)
    assert third.x >= 0
    assert third.x + third.width <= 800
    assert third.y >= 0
    assert third.y + third.height <= 600


def test_extreme_cap_keeps_every_slot_on_screen() -> None:
    # given
    cap = 64

    # when / then
    for slot in range(cap):
        rect = _default_rect(slot)
        assert rect.x >= 0
        assert rect.x + rect.width <= 1920
        assert rect.y >= 0
        assert rect.y + rect.height <= 1080

    # then
    boundary = _default_rect(cap - 1)
    assert (boundary.x, boundary.y) == (460, 214)
