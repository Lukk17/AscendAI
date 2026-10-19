"""Deterministic placement of intervention windows on the shared display.

Each slot maps to a rectangle of the configured window size. Positions
cascade by the configured offset with a wrapping modulus, so however large
the cap is set no window is ever placed partly or wholly off screen. This
module holds no size or offset of its own: every figure is passed in, read
from the settings of task 1.1 by the caller.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowRect:
    """The slot and its rectangle on the shared display."""

    slot: int
    x: int
    y: int
    width: int
    height: int


def parse_display_size(display_size: str) -> tuple[int, int]:
    """Split a `<width>x<height>` display size into its two sides."""
    width_text, _, height_text = display_size.partition("x")

    return int(width_text), int(height_text)


def rect_for_slot(
    slot: int,
    display_size: str,
    window_size: tuple[int, int],
    cascade_offset: int,
) -> WindowRect:
    """Return the rectangle for *slot* under the wrapping cascade.

    Size is constant for every slot; position steps by *cascade_offset*
    per slot and wraps so the rectangle stays fully inside the display.
    """
    display_width, display_height = parse_display_size(display_size)
    window_width, window_height = window_size
    x = (slot * cascade_offset) % (display_width - window_width + 1)
    y = (slot * cascade_offset) % (display_height - window_height + 1)

    return WindowRect(slot=slot, x=x, y=y, width=window_width, height=window_height)
