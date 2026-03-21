"""System message card for informational UI output."""

from __future__ import annotations

from nicegui import ui

from theact.web.styles import SYSTEM_COLOR


def show_system_message(container: ui.element, content: str) -> None:
    """Add a system information card to the chat area."""
    with container:
        with ui.card().classes("w-full").style("opacity: 0.8; border: 1px solid #555;"):
            ui.html(
                f'<div style="color: {SYSTEM_COLOR}; font-size: 0.9em; '
                f'white-space: pre-wrap;">{content}</div>'
            )
