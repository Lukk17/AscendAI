"""Concurrent human-intervention windows on the shared NoVNC display."""

from src.reader.novnc.flow_registry import (
    NoVNCFlow,
    NoVNCFlowRegistry,
    flow_key_for,
    flow_shape,
    novnc_flow_registry,
)
from src.reader.novnc.window_layout import WindowRect, parse_display_size, rect_for_slot

__all__ = [
    "NoVNCFlow",
    "NoVNCFlowRegistry",
    "WindowRect",
    "flow_key_for",
    "flow_shape",
    "novnc_flow_registry",
    "parse_display_size",
    "rect_for_slot",
]
