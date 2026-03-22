"""Collapsible thinking panel for displaying model reasoning."""

from __future__ import annotations

from nicegui import ui

from theact.web.components.message_blocks import StreamingTextBlock
from theact.web.styles import THINKING_COLOR


def create_thinking_panel(
    container: ui.element, label: str = "thinking..."
) -> StreamingTextBlock:
    """Create a collapsible thinking panel inside a turn card.

    Returns a StreamingTextBlock that appends thinking tokens.
    The expansion starts collapsed.
    """
    with container:
        expansion = ui.expansion(label, icon="psychology").classes("w-full")
        expansion.style("color: #888;")
    return StreamingTextBlock(expansion, "", THINKING_COLOR)
