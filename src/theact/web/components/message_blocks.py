"""Message block components: streaming text and static player/narrator/character blocks."""

from __future__ import annotations

import html as html_lib

from nicegui import ui

from theact.web.styles import (
    NARRATOR_COLOR,
    NARRATOR_NAME_COLOR,
    PLAYER_COLOR,
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

    def replace_content(self, text: str) -> None:
        """Replace the entire block content (e.g. after YAML parsing)."""
        self._buffer = [text]
        self._element.content = self._text_to_html(text)

    def _text_to_html(self, text: str) -> str:
        """Convert plain text to safe HTML for display."""
        escaped = html_lib.escape(text)
        formatted = escaped.replace("\n", "<br>")
        return f'<div style="color: {self._color}; white-space: pre-wrap;">{formatted}</div>'


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
            f"color: {PLAYER_COLOR}; font-weight: bold; margin-bottom: 4px;"
        )
        ui.html(
            f'<div style="color: {NARRATOR_COLOR}; white-space: pre-wrap;">'
            f"{html_lib.escape(text)}</div>"
        )
