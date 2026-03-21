"""Collapsible thinking panel for displaying model reasoning."""

from __future__ import annotations

from nicegui import ui

from theact.web.components.message_blocks import StreamingTextBlock
from theact.web.styles import THINKING_COLOR


def create_thinking_panel(container: ui.element) -> StreamingTextBlock:
    """Create a collapsible thinking panel inside a turn card.

    Returns a StreamingTextBlock that appends thinking tokens.
    The expansion starts collapsed.
    """
    with container:
        expansion = ui.expansion("thinking...", icon="psychology").classes("w-full")
        expansion.style("color: #888;")
    return StreamingTextBlock(expansion, "", THINKING_COLOR)
