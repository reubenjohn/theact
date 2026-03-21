"""Turn card creation for the gameplay view."""

from __future__ import annotations

from nicegui import ui


def create_turn_card(
    container: ui.element, turn_number: int, chapter_title: str
) -> ui.card:
    """Create a card element for a single turn."""
    with container:
        card = ui.card().classes("w-full")
        with card:
            ui.label(f"Turn {turn_number} -- {chapter_title}").style(
                "color: #888; font-size: 0.8em; margin-bottom: 8px;"
            )
    return card
