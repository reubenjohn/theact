"""Reusable UI components for the web interface.

Includes StreamingTextBlock for token-by-token display, turn cards,
message blocks, and system message cards.
"""

from __future__ import annotations

import html as html_lib

from nicegui import ui

from theact.web.styles import (
    NARRATOR_COLOR,
    NARRATOR_NAME_COLOR,
    SYSTEM_COLOR,
    THINKING_COLOR,
    get_character_color,
)


class StreamingTextBlock:
    """A text block that supports token-by-token appending.

    Renders accumulated text as HTML inside a `ui.html` element.
    Each call to `append_text` updates the element's content,
    which NiceGUI pushes to the browser via WebSocket.
    """

    def __init__(self, container: ui.element, label: str, color: str) -> None:
        with container:
            if label:
                ui.label(label).style(
                    f"color: {color}; font-weight: bold; margin-bottom: 4px;"
                )
            self._element = ui.html("")
        self._buffer: list[str] = []
        self._color = color

    def append_text(self, token: str) -> None:
        """Append a token and update the displayed HTML."""
        self._buffer.append(token)
        full_text = "".join(self._buffer)
        self._element.content = self._text_to_html(full_text)

    def finish(self) -> None:
        """Final flush -- ensure all buffered text is displayed."""
        if self._buffer:
            full_text = "".join(self._buffer)
            self._element.content = self._text_to_html(full_text)

    def _text_to_html(self, text: str) -> str:
        """Convert plain text to safe HTML for display."""
        escaped = html_lib.escape(text)
        formatted = escaped.replace("\n", "<br>")
        return f'<div style="color: {self._color}; white-space: pre-wrap;">{formatted}</div>'


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


def create_message_block(
    container: ui.element, label: str, color: str
) -> StreamingTextBlock:
    """Create a labeled message block inside a container for streaming."""
    return StreamingTextBlock(container, label, color)


def create_narrator_block(container: ui.element) -> StreamingTextBlock:
    """Create a narrator message block."""
    return StreamingTextBlock(container, "Narrator", NARRATOR_NAME_COLOR)


def create_character_block(
    container: ui.element,
    character_name: str,
    character_list: list[str],
) -> StreamingTextBlock:
    """Create a character message block with the correct color."""
    color = get_character_color(character_name, character_list)
    return StreamingTextBlock(container, character_name, color)


def create_player_block(
    container: ui.element,
    player_name: str,
    text: str,
) -> None:
    """Create a non-streaming player message block."""
    with container:
        ui.label(player_name).style(
            "color: #ffffff; font-weight: bold; margin-bottom: 4px;"
        )
        ui.html(
            f'<div style="color: #cccccc; white-space: pre-wrap;">'
            f"{html_lib.escape(text)}</div>"
        )


def create_thinking_panel(container: ui.element) -> StreamingTextBlock:
    """Create a collapsible thinking panel inside a turn card.

    Returns a StreamingTextBlock that appends thinking tokens.
    The expansion starts collapsed.
    """
    with container:
        expansion = ui.expansion("thinking...", icon="psychology").classes("w-full")
        expansion.style("color: #888;")
    return StreamingTextBlock(expansion, "", THINKING_COLOR)


def show_system_message(container: ui.element, content: str) -> None:
    """Add a system information card to the chat area."""
    with container:
        with ui.card().classes("w-full").style("opacity: 0.8; border: 1px solid #555;"):
            ui.html(
                f'<div style="color: {SYSTEM_COLOR}; font-size: 0.9em; '
                f'white-space: pre-wrap;">{content}</div>'
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
                    "color: #ffffff; font-weight: bold; "
                    "margin-bottom: 4px; margin-top: 8px;"
                )
                ui.html(
                    f'<div style="color: #cccccc; white-space: pre-wrap;">'
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
