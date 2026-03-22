"""Routes streaming tokens to UI components.

Replaces the nested on_token callback closure in the old
GameplaySession._play_turn(). Tracks current section (narrator vs
character) and manages StreamingTextBlock instances.
"""

from __future__ import annotations

from nicegui import ui

from theact.web.components.message_blocks import (
    StreamingTextBlock,
    create_character_block,
    create_narrator_block,
)
from theact.web.components.thinking_panel import create_thinking_panel
from theact.web.styles import MOOD_COLOR, get_character_color


class StreamRenderer:
    """Routes streaming tokens from run_turn() to UI blocks.

    Manages the lifecycle of StreamingTextBlock instances,
    creating new blocks when the section changes (narrator -> character,
    character A -> character B).

    Args:
        turn_card: The UI card element to render into.
        show_thinking: Whether to display thinking tokens.
        character_list: Ordered character stems for color assignment.
        chat_scroll: Optional scroll area for auto-scrolling.
    """

    def __init__(
        self,
        turn_card: ui.element,
        show_thinking: bool,
        character_list: list[str],
        chat_scroll: ui.scroll_area | None = None,
    ) -> None:
        self._turn_card = turn_card
        self._show_thinking = show_thinking
        self._character_list = character_list
        self._chat_scroll = chat_scroll

        # Internal state
        self._current_block: StreamingTextBlock | None = None
        self._current_section: str = "idle"
        self._thinking_section: str = ""
        self._thinking_block: StreamingTextBlock | None = None

        # Narrator-specific: track block + container for post-stream finalization
        self._narrator_block: StreamingTextBlock | None = None
        self._narrator_container: ui.element | None = None

    async def route_token(
        self,
        source: str,
        character: str | None,
        token: str,
        is_thinking: bool,
    ) -> None:
        """Route a streaming token to the appropriate UI block.

        This is the on_token callback passed to run_turn().
        """
        if is_thinking:
            if self._show_thinking:
                thinking_key = f"{source}:{character or ''}"
                if self._thinking_section != thinking_key:
                    self._thinking_section = thinking_key
                    if source == "narrator":
                        label = "thinking... (Narrator)"
                    else:
                        label = f"thinking... ({character or '?'})"
                    self._thinking_block = create_thinking_panel(self._turn_card, label)
                self._thinking_block.append_text(token)
            return

        if source == "narrator":
            if self._current_section != "narrator":
                self._current_section = "narrator"
                # Wrap narrator in a container for post-stream finalization
                with self._turn_card:
                    self._narrator_container = ui.column().classes(
                        "w-full gap-0 narrator-section"
                    )
                self._current_block = create_narrator_block(self._narrator_container)
                self._narrator_block = self._current_block
            self._current_block.append_text(token)
        elif source == "character":
            char_name = character or "?"
            section_key = f"character:{char_name}"
            if self._current_section != section_key:
                self._current_section = section_key
                self._current_block = create_character_block(
                    self._turn_card, char_name, self._character_list
                )
            self._current_block.append_text(token)

        # Auto-scroll on each token
        if self._chat_scroll:
            self._chat_scroll.scroll_to(percent=1.0)

    def finalize_narrator(
        self,
        narration: str,
        mood: str | None,
        responding_characters: list[str],
    ) -> None:
        """Replace raw YAML in the narrator block with parsed content.

        After streaming, the narrator block contains the raw YAML output.
        This replaces it with just the narration text and adds metadata
        badges for mood and responding characters.
        """
        if not self._narrator_block:
            return

        # Replace raw YAML with clean narration text
        self._narrator_block.replace_content(narration)

        # Add metadata row (mood + responding characters) above narration
        if mood or responding_characters:
            self._narrator_meta_row = ui.row().classes(
                "items-center gap-2 narrator-meta"
            )
            self._narrator_meta_row.move(self._narrator_container, target_index=1)
            with self._narrator_meta_row:
                if mood:
                    ui.badge(mood, color="grey-8").props("outline").style(
                        f"font-size: 0.7em; color: {MOOD_COLOR};"
                    )
                if responding_characters:
                    for char in responding_characters:
                        color = get_character_color(char, self._character_list)
                        ui.badge(char).style(
                            f"font-size: 0.7em; background-color: {color}20; "
                            f"color: {color}; border: 1px solid {color}40;"
                        )

    def finish(self) -> None:
        """Finish any active streaming block."""
        if self._current_block:
            self._current_block.finish()
