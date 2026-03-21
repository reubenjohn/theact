"""Gameplay session — thin orchestrator.

Delegates to:
  - TurnRunner for turn execution
  - StreamRenderer for token routing
  - CommandRouter for slash commands
  - GameSessionState for shared state

Owns the UI layout (header, chat area, input bar) and the main
input loop (_on_submit). Everything else is delegated.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from nicegui import ui

from theact.cli.commands import parse_command
from theact.web.command_router import CommandRouter
from theact.web.components.message_blocks import create_player_block
from theact.web.components.static_turn import render_static_turn
from theact.web.components.turn_card import create_turn_card
from theact.web.state import GameSessionState
from theact.web.streaming import StreamRenderer
from theact.web.turn_runner import TurnRunner

logger = logging.getLogger(__name__)


class GameplaySession:
    """Thin orchestrator for the gameplay view.

    Accepts either:
      - state: GameSessionState (new API)
      - game + llm_config (legacy API, creates GameSessionState internally)
    """

    def __init__(
        self,
        state: GameSessionState | None = None,
        on_quit: callable = None,
        # Legacy parameters — kept for backward compat with app.py
        game=None,
        llm_config=None,
    ) -> None:
        if state is not None:
            self._state = state
        else:
            # Legacy path: construct state from separate args
            self._state = GameSessionState(game=game, llm_config=llm_config)

        self._on_quit = on_quit
        self._turn_runner = TurnRunner(self._state)
        self._command_router: CommandRouter | None = None

        # UI references (set during build)
        self._chat_scroll: ui.scroll_area | None = None
        self._chat_area: ui.column | None = None
        self._input_field: ui.input | None = None
        self._send_button: ui.button | None = None
        self._header_label: ui.label | None = None
        self._think_switch: ui.switch | None = None
        self._gameplay_container: ui.column | None = None

    # --- Public properties for backward compat ---

    @property
    def game(self):
        return self._state.game

    @game.setter
    def game(self, value):
        self._state.game = value

    @property
    def show_thinking(self):
        return self._state.show_thinking

    @show_thinking.setter
    def show_thinking(self, value):
        self._state.show_thinking = value

    @property
    def character_list(self) -> list[str]:
        return self._state.character_list

    def build(self, container: ui.element) -> None:
        """Build the gameplay UI inside the given container."""
        with container:
            self._gameplay_container = (
                ui.column()
                .classes("w-full max-w-3xl mx-auto")
                .style("min-height: 100vh;")
            )

            with self._gameplay_container:
                self._build_header()

                self._chat_scroll = (
                    ui.scroll_area()
                    .classes("w-full flex-grow")
                    .style("height: calc(100vh - 140px);")
                )

                with self._chat_scroll:
                    self._chat_area = ui.column().classes("w-full gap-2 p-2")

                self._build_input_bar()

        self._command_router = CommandRouter(self._state, self._chat_area)
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
                    f"{self._state.game.meta.title} -- "
                    f"Turn {self._state.game.state.turn} -- "
                    f"{chapter_title}"
                )
                .style("color: #ccc; font-size: 0.9em;")
                .classes("flex-grow")
            )

            self._think_switch = ui.switch(
                "Thinking", value=self._state.show_thinking
            ).style("color: #999;")
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
        if not self._state.game.conversation:
            return

        turns: dict[int, list] = defaultdict(list)
        for entry in self._state.game.conversation:
            turns[entry.turn].append(entry)

        for turn_num in sorted(turns.keys()):
            entries = turns[turn_num]
            chapter_title = self._current_chapter_title()
            render_static_turn(
                self._chat_area,
                turn_num,
                chapter_title,
                entries,
                self._state.game.state.player_name,
                self._state.character_list,
            )

        if self._chat_scroll:
            self._chat_scroll.scroll_to(percent=1.0)

    async def _on_submit(self) -> None:
        """Handle input submission — route to command or turn."""
        if self._state.processing:
            return

        text = self._input_field.value.strip() if self._input_field.value else ""
        self._input_field.value = ""

        if not text:
            return

        command = parse_command(text)
        if command:
            cmd_name, args = command
            await self._execute_command(cmd_name, args)
            return

        await self._play_turn(text)

    async def _execute_command(self, cmd: str, args: list[str]) -> None:
        """Execute a slash command."""
        if cmd == "quit":
            self._handle_quit()
            return
        if cmd == "think":
            self._handle_think(args)
            if self._chat_scroll:
                self._chat_scroll.scroll_to(percent=1.0)
            return
        if cmd == "retry":
            await self._handle_retry()
            return

        result = self._command_router.execute(cmd, args)

        # For undo, re-render the conversation
        if cmd == "undo" and result and result.success:
            self._chat_area.clear()
            self._render_history()
            self._update_header()

        if self._chat_scroll:
            self._chat_scroll.scroll_to(percent=1.0)

    async def _play_turn(self, player_input: str) -> None:
        """Execute a turn with streaming."""
        self._state.last_player_input = player_input
        self._lock_input()

        turn_card = create_turn_card(
            self._chat_area,
            self._state.game.state.turn + 1,
            self._current_chapter_title(),
        )

        renderer = StreamRenderer(
            turn_card=turn_card,
            show_thinking=self._state.show_thinking,
            character_list=self._state.character_list,
            chat_scroll=self._chat_scroll,
        )

        try:
            with turn_card:
                spinner_row = ui.row().classes("items-center gap-2")
                with spinner_row:
                    ui.spinner("dots", size="sm")
                    ui.label("processing...").style("color: #888; font-size: 0.8em;")
                spinner_row.set_visibility(False)

            result = await self._turn_runner.run(
                player_input=player_input,
                on_token=renderer.route_token,
            )

            renderer.finish()

            create_player_block(
                turn_card, self._state.game.state.player_name, player_input
            )

            # Show turn summary info
            with turn_card:
                info_parts = []
                if result.narrator.mood:
                    info_parts.append(f"Mood: {result.narrator.mood}")
                if result.narrator.responding_characters:
                    char_names = []
                    for cid in result.narrator.responding_characters:
                        c = self._state.game.characters.get(cid)
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

            self._state.reload_game()
            self._update_header()

        except Exception as e:
            logger.exception("Error during turn")
            renderer.finish()
            with turn_card:
                ui.label(f"Error: {e}").style("color: #ff5252; margin-top: 8px;")
            try:
                self._state.reload_game()
            except Exception:
                logger.exception("Failed to reload game from disk")

        finally:
            spinner_row.set_visibility(False)
            self._unlock_input()
            if self._chat_scroll:
                self._chat_scroll.scroll_to(percent=1.0)

    def _handle_think(self, args: list[str]) -> None:
        """Handle /think command."""
        if not args:
            state = "on" if self._state.show_thinking else "off"
            ui.notify(f"Thinking display is {state}.", type="info")
            return

        arg = args[0].lower()
        if arg == "on":
            self._state.show_thinking = True
            if self._think_switch:
                self._think_switch.value = True
            ui.notify("Thinking display enabled.", type="info")
        elif arg == "off":
            self._state.show_thinking = False
            if self._think_switch:
                self._think_switch.value = False
            ui.notify("Thinking display disabled.", type="info")
        else:
            ui.notify("Usage: /think [on|off]", type="warning")

    async def _handle_retry(self) -> None:
        """Undo last turn and replay the same player input."""
        if not self._state.last_player_input:
            ui.notify("No previous input to retry.", type="warning")
            return

        previous_input = self._state.last_player_input

        from theact.commands.logic import cmd_undo

        result = cmd_undo(self._state.game, [])
        if not result.success:
            ui.notify(result.message, type="warning")
            return

        if result.data:
            self._state.game = result.data
        ui.notify(f"Retrying: {previous_input}", type="info")

        self._chat_area.clear()
        self._render_history()
        self._update_header()

        await self._play_turn(previous_input)

    def _on_think_toggle(self, e) -> None:
        """Handle the thinking toggle switch."""
        self._state.show_thinking = e.value

    def _handle_quit(self) -> None:
        """Return to the main menu."""
        if self._on_quit:
            self._on_quit()

    def _lock_input(self) -> None:
        """Disable input during turn processing."""
        self._state.processing = True
        if self._input_field:
            self._input_field.disable()
        if self._send_button:
            self._send_button.disable()

    def _unlock_input(self) -> None:
        """Re-enable input after turn processing."""
        self._state.processing = False
        if self._input_field:
            self._input_field.enable()
            self._input_field.run_method("focus")
        if self._send_button:
            self._send_button.enable()

    def _current_chapter_title(self) -> str:
        """Get the current chapter's display title."""
        chapter_id = self._state.game.state.current_chapter
        chapter = self._state.game.chapters.get(chapter_id)
        return chapter.title if chapter else chapter_id

    def _update_header(self) -> None:
        """Update the header label with current game state."""
        if self._header_label:
            chapter_title = self._current_chapter_title()
            self._header_label.text = (
                f"{self._state.game.meta.title} -- "
                f"Turn {self._state.game.state.turn} -- "
                f"{chapter_title}"
            )

    async def auto_start(self) -> None:
        """If this is a fresh game (turn 0), auto-play the opening."""
        if self._state.game.state.turn == 0:
            await self._play_turn("[game start]")
