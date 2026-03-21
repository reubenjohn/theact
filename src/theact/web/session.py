"""Gameplay session — thin orchestrator.

Delegates to:
  - TurnRunner for turn execution
  - StreamRenderer for token routing
  - CommandRouter for slash commands
  - GameSessionState for shared state
  - SaveLock for multi-tab safety

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
from theact.web.components.turn_card import create_turn_card, create_turn_info_bar
from theact.web.history import TurnHistoryBrowser
from theact.web.safety import SaveLock
from theact.web.sidebar import GameStateSidebar
from theact.web.state import GameSessionState
from theact.web.streaming import StreamRenderer
from theact.web.toolbar import GameplayToolbar
from theact.web.turn_runner import TurnRunner

logger = logging.getLogger(__name__)

# Command hints shown when the user types "/" in the input field.
COMMAND_HINTS: list[tuple[str, str]] = [
    ("undo", "Undo last N turns"),
    ("retry", "Retry last turn"),
    ("save-as", "Fork save"),
    ("history", "Turn history"),
    ("status", "Game status"),
    ("memory", "Character memory"),
    ("conversation", "Recent entries"),
    ("think", "Toggle thinking"),
    ("save", "Save info"),
    ("help", "All commands"),
    ("quit", "Return to menu"),
]


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

        # Save locking for multi-tab safety
        self._save_lock: SaveLock | None = None
        self._read_only = False

        # UI references (set during build)
        self._chat_scroll: ui.scroll_area | None = None
        self._chat_area: ui.column | None = None
        self._input_field: ui.input | None = None
        self._send_button: ui.button | None = None
        self._header_label: ui.label | None = None
        self._think_switch: ui.switch | None = None
        self._gameplay_container: ui.column | None = None
        self._toolbar: GameplayToolbar | None = None
        self._sidebar: GameStateSidebar | None = None
        self._history_browser: TurnHistoryBrowser | None = None
        self._cmd_menu: ui.menu | None = None
        self._open_dialogs: list[ui.dialog] = []

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
        # Acquire save lock for multi-tab safety
        self._acquire_save_lock()

        # Inject responsive CSS and keyboard shortcut prevention
        self._inject_responsive_css()
        self._inject_shortcut_prevention_js()

        with container:
            # Outer wrapper: full-width row with chat column + sidebar
            self._gameplay_container = (
                ui.row()
                .classes("w-full max-w-6xl mx-auto gameplay-container")
                .style("min-height: 100vh;")
            )

            with self._gameplay_container:
                # --- Main chat column (takes remaining space) ---
                chat_column = (
                    ui.column()
                    .classes("flex-grow h-full overflow-hidden chat-column")
                    .style("min-height: 100vh;")
                )

                with chat_column:
                    self._build_header()

                    # --- Toolbar ---
                    self._toolbar = GameplayToolbar(
                        on_undo=self._toolbar_undo,
                        on_retry=self._toolbar_retry,
                        on_save_as=self._toolbar_save_as,
                        on_history=self._toolbar_history,
                        is_processing=lambda: self._state.processing,
                    )
                    self._toolbar.build(chat_column)

                    self._chat_scroll = (
                        ui.scroll_area()
                        .classes("w-full flex-grow")
                        .style("height: calc(100vh - 180px);")
                    )

                    with self._chat_scroll:
                        self._chat_area = ui.column().classes("w-full gap-2 p-2")

                    self._build_input_bar()

                # --- Sidebar ---
                self._sidebar = GameStateSidebar(state=self._state)
                self._sidebar.build(self._gameplay_container)

            # --- History browser (dialog, initially closed) ---
            self._history_browser = TurnHistoryBrowser(
                save_path=self._state.game.save_path,
                current_turn=self._state.game.state.turn,
                on_restore=self._on_history_restore,
            )
            self._history_browser.build(container)

        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()

        # Register lock cleanup on tab close
        if self._save_lock and self._save_lock.is_locked:
            ui.context.client.on_delete(self._release_save_lock)

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

            ui.button(icon="info", on_click=self._toggle_sidebar).props(
                'flat dense aria-label="Toggle game state sidebar"'
            ).tooltip("Toggle game state sidebar (Ctrl+B)").style("color: #999;")

            ui.button("Menu", on_click=self._handle_quit, icon="home").props(
                "flat dense"
            ).style("color: #999;")

    def _build_input_bar(self) -> None:
        """Build the input bar with text field, send button, and command hints."""
        with (
            ui.row()
            .classes("w-full items-center p-2 gap-2 input-bar")
            .style("border-top: 1px solid #444;")
        ):
            # Command hint menu (hidden by default)
            self._cmd_menu = ui.menu().props("auto-close")
            with self._cmd_menu:
                for cmd, desc in COMMAND_HINTS:
                    ui.menu_item(
                        f"/{cmd} — {desc}",
                        on_click=lambda c=cmd: self._insert_command(c),
                    )

            self._input_field = (
                ui.input(placeholder="What do you do?")
                .classes("flex-grow")
                .props("outlined dense dark")
                .on("keydown.enter", self._on_submit)
            )
            self._input_field.on_value_change(self._on_input_change)

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
        if self._read_only:
            ui.notify(
                "This save is open read-only. Cannot submit turns.",
                type="warning",
            )
            return

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

        post_turn_row = None

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

            # Show post-turn processing indicator
            with turn_card:
                post_turn_row = ui.row().classes(
                    "items-center gap-2 post-turn-indicator"
                )
                with post_turn_row:
                    ui.spinner("dots", size="sm")
                    ui.label("Updating world state...").style(
                        "color: #888; font-size: 0.8em;"
                    )

            create_player_block(
                turn_card, self._state.game.state.player_name, player_input
            )

            # Show turn info bar (mood, beats, chapter advancement)
            create_turn_info_bar(
                turn_card,
                mood=result.narrator.mood,
                beats_hit=(result.game_state.beats_hit if result.game_state else []),
                chapter_advanced=result.chapter_advanced,
                new_chapter=result.new_chapter,
            )

            self._state.reload_game()
            self._update_header()

            # Keep history browser in sync with current turn
            if self._history_browser:
                self._history_browser.current_turn = self._state.game.state.turn

        except Exception as e:
            logger.exception("Error during turn")
            renderer.finish()
            self._show_turn_error(turn_card, str(e), player_input)
            try:
                self._state.reload_game()
            except Exception:
                logger.exception("Failed to reload game from disk")

        finally:
            if post_turn_row is not None:
                post_turn_row.delete()
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

    def _toggle_sidebar(self) -> None:
        """Toggle the game state sidebar visibility."""
        if self._sidebar:
            self._sidebar.toggle()

    def _handle_quit(self) -> None:
        """Return to the main menu."""
        self._release_save_lock()
        if self._on_quit:
            self._on_quit()

    def _lock_input(self) -> None:
        """Disable input during turn processing."""
        self._state.processing = True
        if self._input_field:
            self._input_field.disable()
        if self._send_button:
            self._send_button.disable()
        if self._toolbar:
            self._toolbar.set_enabled(False)

    def _unlock_input(self) -> None:
        """Re-enable input after turn processing."""
        self._state.processing = False
        if self._input_field:
            self._input_field.enable()
            self._input_field.run_method("focus")
        if self._send_button:
            self._send_button.enable()
        if self._toolbar:
            self._toolbar.set_enabled(True)

    # --- Toolbar callbacks ---

    async def _toolbar_undo(self, steps: int = 1) -> None:
        """Toolbar undo callback: undo N turns and re-render."""
        from theact.commands.logic import cmd_undo

        result = cmd_undo(self._state.game, [str(steps)])
        if not result.success:
            ui.notify(result.message, type="warning")
            return
        if result.data:
            self._state.game = result.data
        ui.notify(result.message, type="info")
        self._chat_area.clear()
        self._render_history()
        self._update_header()

    async def _toolbar_retry(self) -> None:
        """Toolbar retry callback: undo last turn and replay."""
        await self._handle_retry()

    async def _toolbar_save_as(self, name: str) -> None:
        """Toolbar save-as callback: fork save to new name."""
        from theact.commands.logic import cmd_save_as

        result = cmd_save_as(self._state.game, [name])
        if result.success:
            ui.notify(result.message, type="positive")
        else:
            ui.notify(result.message, type="warning")

    def _toolbar_history(self) -> None:
        """Toolbar history callback: toggle the history browser panel."""
        if self._history_browser:
            self._history_browser.current_turn = self._state.game.state.turn
            self._history_browser.toggle()

    def _on_history_restore(self, steps: int) -> None:
        """Callback after history-based restore. Reloads game and re-renders."""
        self._state.reload_game()
        self._chat_area.clear()
        self._render_history()
        self._update_header()

        # Update the history browser's current turn reference
        if self._history_browser:
            self._history_browser.current_turn = self._state.game.state.turn

    # --- Input helpers ---

    def _on_input_change(self, e) -> None:
        """Show command hints when input starts with '/'."""
        value = e.value or ""
        if value == "/":
            self._cmd_menu.open()
        else:
            self._cmd_menu.close()

    def _insert_command(self, cmd: str) -> None:
        """Insert a command into the input field."""
        self._input_field.value = f"/{cmd} "
        self._input_field.run_method("focus")

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

    # --- Save locking ---

    def _acquire_save_lock(self) -> None:
        """Try to acquire exclusive lock on the save directory."""
        self._save_lock = SaveLock(self._state.game.save_path)
        if not self._save_lock.acquire():
            self._show_lock_conflict_dialog()

    def _release_save_lock(self) -> None:
        """Release the save lock if held."""
        if self._save_lock:
            self._save_lock.release()

    def _show_lock_conflict_dialog(self) -> None:
        """Show dialog when save is locked by another tab."""
        with ui.dialog() as dlg, ui.card():
            ui.label("Save is open in another tab").style(
                "font-weight: bold; color: #ccc;"
            )
            ui.label(
                "This save appears to be open elsewhere. "
                "Opening it here may cause data corruption."
            ).style("color: #999;")
            with ui.row().classes("justify-end gap-2 mt-2"):
                ui.button(
                    "Open Read-Only",
                    on_click=lambda: self._enter_readonly(dlg),
                ).props("flat").style("color: #42a5f5;")
                ui.button(
                    "Force Unlock",
                    on_click=lambda: self._force_unlock(dlg),
                ).props("flat").style("color: #ffa726;")
                ui.button(
                    "Back to Menu",
                    on_click=lambda: self._back_to_menu(dlg),
                ).props("flat").style("color: #999;")
        self._open_dialogs.append(dlg)
        dlg.open()

    def _enter_readonly(self, dlg: ui.dialog) -> None:
        """Enter read-only mode (no turns, no commands that write)."""
        dlg.close()
        self._read_only = True
        ui.notify("Opened in read-only mode.", type="info")

    def _force_unlock(self, dlg: ui.dialog) -> None:
        """Force-acquire the lock, breaking any existing hold."""
        dlg.close()
        if self._save_lock and self._save_lock.force_acquire():
            self._read_only = False
            ui.notify("Lock acquired. You have full control.", type="positive")
        else:
            ui.notify("Failed to acquire lock.", type="negative")
            self._read_only = True

    def _back_to_menu(self, dlg: ui.dialog) -> None:
        """Close dialog and return to menu."""
        dlg.close()
        if self._on_quit:
            self._on_quit()

    # --- Keyboard shortcuts ---

    def _setup_keyboard_shortcuts(self) -> None:
        """Register keyboard shortcuts for common actions."""
        ui.keyboard(on_key=self._handle_key, ignore=[])

    async def _handle_key(self, e) -> None:
        """Handle keyboard shortcuts. Only acts on modifier combos."""
        if not e.action.keydown:
            return

        if e.modifiers.ctrl or e.modifiers.meta:
            if e.key == "z":
                await self._shortcut_undo()
            elif e.key == "s":
                self._shortcut_save_as()
            elif e.key == "h":
                self._shortcut_toggle_history()
            elif e.key == "b":
                self._shortcut_toggle_sidebar()
        elif e.key.escape:
            self._close_open_dialogs()

    async def _shortcut_undo(self) -> None:
        """Ctrl+Z: show undo confirmation dialog."""
        if self._state.processing or self._read_only:
            return
        from theact.web.components.dialogs import confirm_dialog

        confirm_dialog(
            title="Undo Last Turn",
            message="Undo the most recent turn? This cannot be reversed.",
            on_confirm=lambda: self._toolbar_undo(1),
            confirm_text="Undo",
            confirm_color="#ff9800",
        )

    def _shortcut_save_as(self) -> None:
        """Ctrl+S: open save-as dialog."""
        if self._state.processing:
            return
        if self._toolbar:
            self._toolbar._show_save_as_dialog()

    def _shortcut_toggle_history(self) -> None:
        """Ctrl+H: toggle history browser."""
        self._toolbar_history()

    def _shortcut_toggle_sidebar(self) -> None:
        """Ctrl+B: toggle sidebar."""
        self._toggle_sidebar()

    def _close_open_dialogs(self) -> None:
        """Escape: close any open dialogs and the history browser."""
        for dlg in self._open_dialogs:
            try:
                dlg.close()
            except Exception:
                pass
        self._open_dialogs.clear()

        if self._history_browser and self._history_browser._dialog:
            if self._history_browser._dialog.value:
                self._history_browser.close()

    # --- Error retry ---

    def _show_turn_error(
        self, turn_card: ui.element, error_msg: str, player_input: str
    ) -> None:
        """Show error with retry button in the turn card."""
        with turn_card:
            ui.label(f"Error: {error_msg}").style("color: #ff5252; margin-top: 8px;")
            ui.button(
                "Retry",
                icon="refresh",
                on_click=lambda: self._retry_failed_turn(player_input),
            ).props("flat dense").style("color: #ffa726; margin-top: 4px;").tooltip(
                "Retry with the same input"
            )

    async def _retry_failed_turn(self, player_input: str) -> None:
        """Retry a failed turn: reload state from disk and replay."""
        try:
            self._state.reload_game()
        except Exception:
            logger.exception("Failed to reload game for retry")
            ui.notify("Could not reload game state.", type="negative")
            return

        # Re-render conversation history (removes the failed turn card)
        self._chat_area.clear()
        self._render_history()
        self._update_header()

        # Replay the turn
        await self._play_turn(player_input)

    # --- Responsive CSS ---

    def _inject_responsive_css(self) -> None:
        """Inject responsive CSS media queries for mobile/tablet layouts."""
        ui.add_css("""
/* Mobile: <768px */
@media (max-width: 767px) {
    .game-sidebar {
        display: none !important;
    }
    .turn-card {
        padding: 0.5rem !important;
    }
    .input-bar {
        flex-direction: column;
    }
    .input-bar .q-input {
        width: 100% !important;
    }
    .input-bar .q-btn {
        width: 100% !important;
        margin-top: 0.25rem;
    }
    .toolbar-extras {
        display: none !important;
    }
    .gameplay-container {
        flex-direction: column !important;
    }
}

/* Tablet: 768-1024px */
@media (min-width: 768px) and (max-width: 1024px) {
    .game-sidebar {
        width: 250px !important;
        min-width: 250px !important;
    }
    .toolbar-extras {
        display: none !important;
    }
}
""")

    def _inject_shortcut_prevention_js(self) -> None:
        """Inject JavaScript to prevent browser defaults for shortcuts."""
        ui.run_javascript("""
document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && ['s', 'h', 'b'].includes(e.key)) {
        e.preventDefault();
    }
});
""")
