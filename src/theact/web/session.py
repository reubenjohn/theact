"""Gameplay view: chat display, streaming, input handling, commands.

This module creates the gameplay interface and manages a single
play session. It uses the same turn engine as the CLI (run_turn()
with a StreamCallback).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from nicegui import ui

from theact.cli.commands import parse_command
from theact.engine.turn import run_turn
from theact.io.save_manager import load_save
from theact.llm.config import LLMConfig
from theact.models.game import LoadedGame
from theact.web.commands import (
    cmd_conversation_web,
    cmd_help_web,
    cmd_history_web,
    cmd_memory_web,
    cmd_save_web,
    cmd_status_web,
    cmd_undo_web,
)
from theact.web.components import (
    create_character_block,
    create_narrator_block,
    create_player_block,
    create_thinking_panel,
    create_turn_card,
    render_static_turn,
)

logger = logging.getLogger(__name__)


class GameplaySession:
    """Manages the web gameplay view for a single loaded game.

    Responsible for:
    - Rendering conversation history on load
    - Handling player input and slash commands
    - Streaming turn output to the UI
    - Input locking during turn processing
    """

    def __init__(
        self,
        game: LoadedGame,
        llm_config: LLMConfig,
        on_quit: callable,
    ) -> None:
        self.game = game
        self.llm_config = llm_config
        self.on_quit = on_quit
        self.show_thinking = True
        self._last_player_input: str | None = None
        self._processing = False

        # UI references (set during build)
        self._chat_scroll: ui.scroll_area | None = None
        self._chat_area: ui.column | None = None
        self._input_field: ui.input | None = None
        self._send_button: ui.button | None = None
        self._header_label: ui.label | None = None
        self._think_switch: ui.switch | None = None
        self._gameplay_container: ui.column | None = None

    @property
    def character_list(self) -> list[str]:
        """Ordered list of character stems for color assignment."""
        return list(self.game.characters.keys())

    def build(self, container: ui.element) -> None:
        """Build the gameplay UI inside the given container."""
        with container:
            self._gameplay_container = (
                ui.column()
                .classes("w-full max-w-3xl mx-auto")
                .style("min-height: 100vh;")
            )

            with self._gameplay_container:
                # --- Header bar ---
                self._build_header()

                # --- Chat area ---
                self._chat_scroll = (
                    ui.scroll_area()
                    .classes("w-full flex-grow")
                    .style("height: calc(100vh - 140px);")
                )

                with self._chat_scroll:
                    self._chat_area = ui.column().classes("w-full gap-2 p-2")

                # --- Input bar ---
                self._build_input_bar()

        # Render conversation history
        self._render_history()

    def _build_header(self) -> None:
        """Build the header bar with game info and controls."""
        with (
            ui.row()
            .classes("w-full items-center p-2")
            .style("border-bottom: 1px solid #444;")
        ):
            chapter_title = self._current_chapter_title()
            self._header_label = (
                ui.label(
                    f"{self.game.meta.title} -- Turn {self.game.state.turn} -- "
                    f"{chapter_title}"
                )
                .style("color: #ccc; font-size: 0.9em;")
                .classes("flex-grow")
            )

            self._think_switch = ui.switch("Thinking", value=self.show_thinking).style(
                "color: #999;"
            )
            self._think_switch.on_value_change(self._on_think_toggle)

            ui.button("Menu", on_click=self._handle_quit, icon="home").props(
                "flat dense"
            ).style("color: #999;")

    def _build_input_bar(self) -> None:
        """Build the input bar with text field and send button."""
        with (
            ui.row()
            .classes("w-full items-center p-2 gap-2")
            .style("border-top: 1px solid #444;")
        ):
            self._input_field = (
                ui.input(placeholder="What do you do?")
                .classes("flex-grow")
                .props("outlined dense dark")
                .on("keydown.enter", self._on_submit)
            )
            self._send_button = ui.button(
                "Send", on_click=self._on_submit, icon="send"
            ).props("dense")

    def _render_history(self) -> None:
        """Render existing conversation history as static turn cards."""
        if not self.game.conversation:
            return

        # Group entries by turn number
        turns: dict[int, list] = defaultdict(list)
        for entry in self.game.conversation:
            turns[entry.turn].append(entry)

        for turn_num in sorted(turns.keys()):
            entries = turns[turn_num]
            chapter_title = self._current_chapter_title()
            render_static_turn(
                self._chat_area,
                turn_num,
                chapter_title,
                entries,
                self.game.state.player_name,
                self.character_list,
            )

        # Scroll to bottom after rendering history
        if self._chat_scroll:
            self._chat_scroll.scroll_to(percent=1.0)

    async def _on_submit(self) -> None:
        """Handle input submission (Enter key or Send button)."""
        if self._processing:
            return

        text = self._input_field.value.strip() if self._input_field.value else ""
        self._input_field.value = ""

        if not text:
            return

        # Check for slash command
        command = parse_command(text)
        if command:
            cmd_name, args = command
            await self._execute_command(cmd_name, args)
            return

        # Normal player input
        await self._play_turn(text)

    async def _play_turn(self, player_input: str) -> None:
        """Run a turn through the engine, streaming results to the UI."""
        self._last_player_input = player_input
        self._lock_input()

        chapter_title = self._current_chapter_title()
        turn_card = create_turn_card(
            self._chat_area, self.game.state.turn + 1, chapter_title
        )

        # Create thinking panel (for future use when thinking tokens
        # are separated in the callback). Currently, thinking tokens are
        # consumed internally by agents and not passed through on_token.
        create_thinking_panel(turn_card)

        # Track streaming state
        current_block: list = [None]  # mutable reference
        current_section: list = ["idle"]

        async def on_token(source: str, character: str | None, token: str) -> None:
            """Stream callback: route tokens to UI components."""
            if source == "narrator":
                if current_section[0] != "narrator":
                    current_section[0] = "narrator"
                    current_block[0] = create_narrator_block(turn_card)
                current_block[0].append_text(token)
            elif source == "character":
                char_name = character or "?"
                section_key = f"character:{char_name}"
                if current_section[0] != section_key:
                    current_section[0] = section_key
                    current_block[0] = create_character_block(
                        turn_card, char_name, self.character_list
                    )
                current_block[0].append_text(token)

            # Auto-scroll on each token
            if self._chat_scroll:
                self._chat_scroll.scroll_to(percent=1.0)

        try:
            # Create a spinner row (hidden until post-processing starts)
            with turn_card:
                spinner_row = ui.row().classes("items-center gap-2")
                with spinner_row:
                    ui.spinner("dots", size="sm")
                    ui.label("processing...").style("color: #888; font-size: 0.8em;")
                spinner_row.set_visibility(False)

            result = await run_turn(
                self.game,
                player_input,
                self.llm_config,
                on_token=on_token,
            )

            # Finish any active streaming block
            if current_block[0]:
                current_block[0].finish()

            # Add player message to the turn card
            create_player_block(turn_card, self.game.state.player_name, player_input)

            # Show turn summary info
            with turn_card:
                info_parts = []
                if result.narrator.mood:
                    info_parts.append(f"Mood: {result.narrator.mood}")
                if result.narrator.responding_characters:
                    char_names = []
                    for cid in result.narrator.responding_characters:
                        c = self.game.characters.get(cid)
                        char_names.append(c.name if c else cid)
                    info_parts.append(f"Characters: {', '.join(char_names)}")
                if result.game_state and result.game_state.beats_hit:
                    info_parts.append(
                        f"Beats: {', '.join(result.game_state.beats_hit)}"
                    )
                if result.chapter_advanced:
                    info_parts.append(f"Chapter advanced to: {result.new_chapter}")
                if info_parts:
                    ui.label(" | ".join(info_parts)).style(
                        "color: #666; font-size: 0.75em; margin-top: 8px;"
                    )

            # Reload game from disk
            self._reload_game()
            self._update_header()

        except Exception as e:
            logger.exception("Error during turn")
            with turn_card:
                ui.label(f"Error: {e}").style("color: #ff5252; margin-top: 8px;")
            # Reload from disk to discard partial mutations
            self._reload_game()

        finally:
            # Remove spinner
            spinner_row.set_visibility(False)
            self._unlock_input()

            # Auto-scroll to bottom
            if self._chat_scroll:
                self._chat_scroll.scroll_to(percent=1.0)

    async def _execute_command(self, cmd: str, args: list[str]) -> None:
        """Execute a slash command and render output to the chat area."""
        if cmd == "help":
            cmd_help_web(self._chat_area)
        elif cmd == "quit":
            self._handle_quit()
        elif cmd == "undo":
            await self._cmd_undo(args)
        elif cmd == "history":
            cmd_history_web(self._chat_area, self.game)
        elif cmd == "save":
            cmd_save_web(self._chat_area, self.game)
        elif cmd == "status":
            cmd_status_web(self._chat_area, self.game)
        elif cmd == "memory":
            cmd_memory_web(self._chat_area, self.game, args)
        elif cmd == "think":
            self._cmd_think(args)
        elif cmd == "retry":
            await self._cmd_retry()
        elif cmd == "conversation":
            cmd_conversation_web(self._chat_area, self.game, args)
        else:
            ui.notify(
                f"Unknown command: /{cmd}. Type /help for available commands.",
                type="warning",
            )

        # Scroll to bottom after command output
        if self._chat_scroll:
            self._chat_scroll.scroll_to(percent=1.0)

    async def _cmd_undo(self, args: list[str]) -> None:
        """Handle /undo command: rewind and re-render conversation."""
        reloaded, message = cmd_undo_web(self.game, args)
        if reloaded is None:
            ui.notify(message, type="warning")
            return

        self.game = reloaded
        ui.notify(message, type="info")

        # Clear and re-render conversation
        self._chat_area.clear()
        self._render_history()
        self._update_header()

    def _cmd_think(self, args: list[str]) -> None:
        """Handle /think command."""
        if not args:
            state = "on" if self.show_thinking else "off"
            ui.notify(f"Thinking display is {state}.", type="info")
            return

        arg = args[0].lower()
        if arg == "on":
            self.show_thinking = True
            if self._think_switch:
                self._think_switch.value = True
            ui.notify("Thinking display enabled.", type="info")
        elif arg == "off":
            self.show_thinking = False
            if self._think_switch:
                self._think_switch.value = False
            ui.notify("Thinking display disabled.", type="info")
        else:
            ui.notify("Usage: /think [on|off]", type="warning")

    async def _cmd_retry(self) -> None:
        """Undo last turn and replay the same player input."""
        if self._last_player_input is None:
            ui.notify("No previous input to retry.", type="warning")
            return

        previous_input = self._last_player_input

        # Undo last turn
        reloaded, message = cmd_undo_web(self.game, [])
        if reloaded is None:
            ui.notify(message, type="warning")
            return

        self.game = reloaded
        ui.notify(f"Retrying: {previous_input}", type="info")

        # Clear and re-render, then replay
        self._chat_area.clear()
        self._render_history()
        self._update_header()

        await self._play_turn(previous_input)

    def _on_think_toggle(self, e) -> None:
        """Handle the thinking toggle switch."""
        self.show_thinking = e.value

    def _handle_quit(self) -> None:
        """Return to the main menu."""
        if self.on_quit:
            self.on_quit()

    def _lock_input(self) -> None:
        """Disable input during turn processing."""
        self._processing = True
        if self._input_field:
            self._input_field.disable()
        if self._send_button:
            self._send_button.disable()

    def _unlock_input(self) -> None:
        """Re-enable input after turn processing."""
        self._processing = False
        if self._input_field:
            self._input_field.enable()
            self._input_field.run_method("focus")
        if self._send_button:
            self._send_button.enable()

    def _current_chapter_title(self) -> str:
        """Get the current chapter's display title."""
        chapter_id = self.game.state.current_chapter
        chapter = self.game.chapters.get(chapter_id)
        return chapter.title if chapter else chapter_id

    def _update_header(self) -> None:
        """Update the header label with current game state."""
        if self._header_label:
            chapter_title = self._current_chapter_title()
            self._header_label.text = (
                f"{self.game.meta.title} -- Turn {self.game.state.turn} -- "
                f"{chapter_title}"
            )

    def _reload_game(self) -> None:
        """Reload game from disk, discarding in-memory state."""
        try:
            self.game = load_save(self.game.save_path.name, self.game.save_path.parent)
        except Exception:
            logger.exception("Failed to reload game from disk")

    async def auto_start(self) -> None:
        """If this is a fresh game (turn 0), auto-play the opening."""
        if self.game.state.turn == 0:
            await self._play_turn("[game start]")
