"""Static (non-streaming) rendering of complete past turns."""

from __future__ import annotations

import html as html_lib

from nicegui import ui

from theact.web.components.turn_card import create_turn_card
from theact.web.styles import (
    NARRATOR_COLOR,
    NARRATOR_NAME_COLOR,
    PLAYER_COLOR,
    get_character_color,
)


def render_static_turn(
    container: ui.element,
    turn_number: int,
    chapter_title: str,
    entries: list,
    player_name: str,
    character_list: list[str],
) -> None:
    """Render a complete past turn as a static (non-streaming) card.

    Args:
        container: Parent UI element to add the card into.
        turn_number: Turn number for the header.
        chapter_title: Chapter title for the header.
        entries: List of ConversationEntry objects for this turn.
        player_name: The player's display name.
        character_list: Ordered list of character stems for color lookup.
    """
    card = create_turn_card(container, turn_number, chapter_title)

    for entry in entries:
        if entry.role == "narrator":
            with card:
                ui.label("Narrator").style(
                    f"color: {NARRATOR_NAME_COLOR}; font-weight: bold; "
                    f"margin-bottom: 4px; margin-top: 8px;"
                )
                ui.html(
                    f'<div style="color: {NARRATOR_COLOR}; white-space: pre-wrap;">'
                    f"{html_lib.escape(entry.content)}</div>"
                )
        elif entry.role == "player":
            with card:
                ui.label(player_name).style(
                    f"color: {PLAYER_COLOR}; font-weight: bold; "
                    "margin-bottom: 4px; margin-top: 8px;"
                )
                ui.html(
                    f'<div style="color: {NARRATOR_COLOR}; white-space: pre-wrap;">'
                    f"{html_lib.escape(entry.content)}</div>"
                )
        elif entry.role == "character":
            name = entry.character or "?"
            color = get_character_color(name, character_list)
            with card:
                ui.label(name).style(
                    f"color: {color}; font-weight: bold; "
                    f"margin-bottom: 4px; margin-top: 8px;"
                )
                ui.html(
                    f'<div style="color: {color}; white-space: pre-wrap;">'
                    f"{html_lib.escape(entry.content)}</div>"
                )
