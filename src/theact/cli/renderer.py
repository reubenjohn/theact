"""Rich-based rendering for streaming turn output."""

from __future__ import annotations

from rich.console import Console
from rich.rule import Rule
from rich.style import Style
from rich.text import Text

from theact.cli.styles import (
    ERROR_STYLE,
    NARRATOR_STYLE,
    STATUS_STYLE,
    THINKING_LABEL_STYLE,
    THINKING_STYLE,
    TURN_SEPARATOR,
    get_character_color,
)
from theact.models.game import LoadedGame


class RenderState:
    """Track which section we are currently rendering."""

    IDLE = "idle"
    THINKING = "thinking"
    NARRATOR = "narrator"
    CHARACTER = "character"
    POST_PROCESSING = "post_processing"


class Renderer:
    """Handles all visual output during gameplay.

    The renderer streams tokens to the terminal as they arrive,
    using Rich's Console.print(end="") for inline streaming without
    flickering. It tracks which section (thinking/narrator/character)
    we are currently in to handle transitions with appropriate spacing
    and labels.
    """

    def __init__(self, console: Console, game: LoadedGame) -> None:
        self.console = console
        self.game = game
        self.character_list = list(game.characters.keys())
        self._section = RenderState.IDLE
        self._current_character: str | None = None
        self._status_ctx = None

    def begin_turn(self, turn_number: int, chapter_title: str) -> None:
        """Print the turn header rule."""
        self.console.print()
        self.console.print(
            Rule(f" Turn {turn_number} \u00b7 {chapter_title} ", style=TURN_SEPARATOR)
        )
        self.console.print()
        self._section = RenderState.IDLE
        self._current_character = None

    def end_turn(self) -> None:
        """Print the turn footer rule."""
        self.console.print()
        self.console.print(Rule(style=TURN_SEPARATOR))
        self.console.print()
        self._section = RenderState.IDLE
        self._current_character = None

    def render_thinking(self, text: str, show: bool, label: str = "thinking") -> None:
        """Render thinking tokens if enabled."""
        if not show:
            return
        if self._section != RenderState.THINKING:
            self._transition_to(RenderState.THINKING)
            self.console.print(Text(f"  \u2bff {label}...", style=THINKING_LABEL_STYLE))
        self.console.print(Text(text, style=THINKING_STYLE), end="")

    def render_narrator(self, text: str) -> None:
        """Render a narrator content token."""
        self._transition_to(RenderState.NARRATOR)
        self.console.print(Text(text, style=NARRATOR_STYLE), end="")

    def end_narrator(self) -> None:
        """Signal end of narrator block."""
        self.console.print()  # newline after narrator block

    def render_character(self, character_name: str, text: str) -> None:
        """Render a character content token."""
        self._transition_to_character(character_name)
        color = get_character_color(character_name, self.character_list)
        self.console.print(Text(text, style=Style(color=color)), end="")

    def end_character(self) -> None:
        """Signal end of a character block."""
        self.console.print()  # newline after character block

    def start_post_processing(self) -> None:
        """Show a post-processing spinner."""
        self._transition_to(RenderState.POST_PROCESSING)
        self._status_ctx = self.console.status(
            "  updating world state...", spinner="dots", style=STATUS_STYLE
        )
        self._status_ctx.__enter__()

    def stop_post_processing(self) -> None:
        """Stop the post-processing spinner."""
        if self._status_ctx is not None:
            self._status_ctx.__exit__(None, None, None)
            self._status_ctx = None
        self._section = RenderState.IDLE

    def show_error(self, message: str) -> None:
        """Display an error message. Stops spinner if active."""
        self.stop_post_processing()
        self.console.print()
        self.console.print(f"  Error: {message}", style=ERROR_STYLE)
        self.console.print()

    def _transition_to(self, new_section: str) -> None:
        """Handle section transitions with appropriate spacing."""
        if self._section == new_section:
            return
        if self._section != RenderState.IDLE:
            self.console.print()  # end current inline stream
            self.console.print()  # blank line between sections
        self._section = new_section

    def _transition_to_character(self, name: str) -> None:
        """Handle transition into a character section, printing name label."""
        if self._section == RenderState.CHARACTER and self._current_character == name:
            return  # still same character, keep streaming
        self._transition_to(RenderState.CHARACTER)
        self._current_character = name
        color = get_character_color(name, self.character_list)
        # Look up display name from game characters
        char = self.game.characters.get(name)
        label = char.name if char else name
        self.console.print(Text(f"  {label}", style=Style(color=color, bold=True)))
