"""Turn history browser: timeline, peek viewer, diff viewer, restore.

Opened from the gameplay toolbar. Reads git history from the
current save via git_save APIs. Renders as a dialog overlay
(NiceGUI dialogs can be created from any nesting level, unlike
drawers which must be direct page children).
"""

from __future__ import annotations

import html as html_lib
import logging
from datetime import datetime
from pathlib import Path

import yaml
from nicegui import ui

from theact.versioning import git_save
from theact.versioning.git_save import TurnInfo
from theact.web.styles import (
    ERROR_COLOR,
    INFO_COLOR,
    SUCCESS_COLOR,
    WARNING_ACCENT_COLOR,
)

logger = logging.getLogger(__name__)


class TurnHistoryBrowser:
    """Visual turn history browser with timeline, peek, and diff.

    Opens as a full-screen dialog. Provides three views:
    - Timeline: list of all past turns from git history
    - Peek: read-only snapshot of a historical turn's game state
    - Diff: unified diff between two selected turns
    """

    def __init__(
        self,
        save_path: Path,
        current_turn: int,
        on_restore: callable,  # callback(steps: int) -> None
    ) -> None:
        self.save_path = save_path
        self.current_turn = current_turn
        self.on_restore = on_restore

        # UI references
        self._dialog: ui.dialog | None = None
        self._timeline_container: ui.column | None = None
        self._detail_container: ui.column | None = None

        # State
        self._history: list[TurnInfo] = []
        self._selected_turns: list[int] = []  # For diff mode (max 2)
        self._diff_mode: bool = False

    def build(self, parent: ui.element) -> None:
        """Build the history browser as a dialog (initially closed)."""
        self._dialog = ui.dialog().props("maximized").style("background: #1e1e1e;")

        with self._dialog:
            with (
                ui.card()
                .classes("w-full h-full q-pa-md")
                .style("background: #1e1e1e; max-width: 800px; margin: 0 auto;")
                .props('data-testid="history-browser"')
            ):
                self._build_header()

                with (
                    ui.scroll_area()
                    .classes("w-full")
                    .style("height: calc(100vh - 80px);")
                ):
                    self._timeline_container = ui.column().classes("w-full gap-1")
                    ui.separator()
                    self._detail_container = ui.column().classes("w-full")

    def toggle(self) -> None:
        """Toggle the history browser open/closed."""
        if self._dialog:
            if self._dialog.value:
                self.close()
            else:
                self.open()

    def open(self) -> None:
        """Open the dialog and refresh the timeline."""
        self._diff_mode = False
        self._selected_turns.clear()
        self._refresh_timeline()
        if self._detail_container:
            self._detail_container.clear()
        if self._dialog:
            self._dialog.open()

    def close(self) -> None:
        """Close the dialog."""
        if self._dialog:
            self._dialog.close()

    def refresh(self) -> None:
        """Refresh the timeline data."""
        self._refresh_timeline()

    # --- Header ---

    def _build_header(self) -> None:
        """Build the header with title and mode toggle."""
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Turn History").style(
                "color: #ccc; font-weight: bold; font-size: 1.1em;"
            )
            with ui.row().classes("gap-1"):
                ui.button(icon="compare_arrows", on_click=self._toggle_diff_mode).props(
                    "flat dense"
                ).style("color: #999;").tooltip("Compare two turns")
                ui.button(icon="close", on_click=self.close).props("flat dense").style(
                    "color: #999;"
                )

    # --- Timeline ---

    def _refresh_timeline(self) -> None:
        """Reload git history and render the timeline."""
        try:
            self._history = git_save.get_history(self.save_path)
        except Exception as e:
            logger.warning("Failed to load history: %s", e)
            self._history = []

        self._selected_turns.clear()

        if self._timeline_container:
            self._timeline_container.clear()

        if not self._history:
            with self._timeline_container:
                ui.label("No turns yet.").style("color: #888;")
            return

        with self._timeline_container:
            for entry in self._history:  # Most recent first (git log order)
                self._build_turn_entry(entry)

    def _build_turn_entry(self, entry: TurnInfo) -> None:
        """Build a single turn entry in the timeline."""
        # Parse timestamp for display
        try:
            ts = datetime.fromisoformat(entry.timestamp)
            time_str = ts.strftime("%H:%M")
        except (ValueError, TypeError):
            time_str = "?"

        # Truncate commit message to summary
        summary = entry.message.replace(f"Turn {entry.turn}: ", "", 1)
        if len(summary) > 60:
            summary = summary[:57] + "..."

        is_current = entry.turn == self.current_turn

        with (
            ui.card()
            .classes("w-full")
            .style(
                f"background: {'#2d3748' if is_current else '#252525'}; "
                f"border-left: 3px solid {SUCCESS_COLOR if is_current else '#555'}; "
                f"padding: 8px; cursor: pointer;"
            )
        ):
            with ui.row().classes("w-full items-center"):
                # Turn number badge
                ui.badge(str(entry.turn)).style(
                    f"background: {SUCCESS_COLOR if is_current else '#555'}; "
                    f"color: {'#000' if is_current else '#ccc'};"
                )
                # Summary and time
                with ui.column().classes("flex-grow gap-0"):
                    ui.label(summary).style("color: #ccc; font-size: 0.85em;")
                    ui.label(time_str).style("color: #666; font-size: 0.75em;")

                # Action buttons
                if self._diff_mode:
                    self._build_diff_select_button(entry)
                else:
                    self._build_turn_actions(entry)

    def _build_turn_actions(self, entry: TurnInfo) -> None:
        """Build View and Restore buttons for a turn entry."""
        turn_num = entry.turn

        def make_view_handler(t: int):
            def handler():
                self._show_peek(t)

            return handler

        def make_restore_handler(t: int):
            def handler():
                self._confirm_restore(t)

            return handler

        with ui.row().classes("gap-0"):
            ui.button(icon="visibility", on_click=make_view_handler(turn_num)).props(
                "flat dense round"
            ).style(f"color: {INFO_COLOR};").tooltip("View snapshot")

            if turn_num < self.current_turn:
                ui.button(
                    icon="restore", on_click=make_restore_handler(turn_num)
                ).props("flat dense round").style(
                    f"color: {WARNING_ACCENT_COLOR};"
                ).tooltip("Restore to here")

    # --- Peek Viewer ---

    def _show_peek(self, turn_number: int) -> None:
        """Display a read-only snapshot of a historical turn."""
        if self._detail_container:
            self._detail_container.clear()

        try:
            files = git_save.peek_at_turn(self.save_path, turn_number)
        except ValueError as e:
            with self._detail_container:
                ui.label(f"Error: {e}").style(f"color: {ERROR_COLOR};")
            return

        with self._detail_container:
            ui.label(f"Turn {turn_number} -- Historical Snapshot (read-only)").style(
                f"color: {WARNING_ACCENT_COLOR}; font-weight: bold; font-size: 0.95em; "
                "margin-bottom: 8px;"
            )

            # Game State (state.yaml)
            if "state.yaml" in files:
                self._render_state_panel(files["state.yaml"])

            # Conversation (conversation.yaml)
            if "conversation.yaml" in files:
                self._render_conversation_panel(files["conversation.yaml"], turn_number)

            # Character Memories (memory/*.yaml)
            memory_files = {k: v for k, v in files.items() if k.startswith("memory/")}
            if memory_files:
                self._render_memories_panel(memory_files)

    def _render_state_panel(self, state_yaml: str) -> None:
        """Render game state from state.yaml content."""
        with ui.expansion("Game State", icon="flag").classes("w-full"):
            try:
                state = yaml.safe_load(state_yaml)
                if isinstance(state, dict):
                    items = [
                        f"Turn: {state.get('turn', '?')}",
                        f"Chapter: {state.get('current_chapter', '?')}",
                        f"Player: {state.get('player_name', '?')}",
                    ]
                    beats = state.get("beats_hit", [])
                    if beats:
                        items.append(f"Beats: {', '.join(beats)}")
                    flags = state.get("flags", {})
                    if flags:
                        items.append(f"Flags: {flags}")
                    for item in items:
                        ui.label(item).style("color: #ccc; font-size: 0.85em;")
                else:
                    ui.code(state_yaml, language="yaml").classes("w-full")
            except yaml.YAMLError:
                ui.code(state_yaml, language="yaml").classes("w-full")

    def _render_conversation_panel(self, conv_yaml: str, turn_number: int) -> None:
        """Render conversation entries for the specified turn."""
        with ui.expansion("Conversation", icon="chat").classes("w-full"):
            try:
                entries = yaml.safe_load(conv_yaml)
                if isinstance(entries, list):
                    turn_entries = [e for e in entries if e.get("turn") == turn_number]
                    if not turn_entries:
                        ui.label("No entries for this turn.").style("color: #888;")
                        return
                    for entry in turn_entries:
                        role = entry.get("role", "?")
                        character = entry.get("character", "")
                        content = entry.get("content", "")
                        if len(content) > 300:
                            content = content[:297] + "..."
                        label = character if role == "character" else role.capitalize()
                        ui.label(f"{label}: {content}").style(
                            "color: #ccc; font-size: 0.85em; margin-bottom: 4px;"
                        )
                else:
                    ui.code(conv_yaml, language="yaml").classes("w-full")
            except yaml.YAMLError:
                ui.code(conv_yaml, language="yaml").classes("w-full")

    def _render_memories_panel(self, memory_files: dict[str, str]) -> None:
        """Render character memory snapshots."""
        with ui.expansion("Character Memories", icon="psychology").classes("w-full"):
            for filepath, content in sorted(memory_files.items()):
                char_name = filepath.replace("memory/", "").replace(".yaml", "")
                try:
                    mem = yaml.safe_load(content)
                    if isinstance(mem, dict):
                        summary = mem.get("summary", "No summary")
                        facts = mem.get("key_facts", [])
                        ui.label(f"{mem.get('character', char_name)}").style(
                            f"color: {SUCCESS_COLOR}; font-weight: bold; font-size: 0.85em;"
                        )
                        ui.label(f"  {summary}").style("color: #ccc; font-size: 0.8em;")
                        for fact in facts[:5]:
                            ui.label(f"  - {fact}").style(
                                "color: #999; font-size: 0.8em;"
                            )
                    else:
                        ui.code(content, language="yaml").classes("w-full")
                except yaml.YAMLError:
                    ui.code(content, language="yaml").classes("w-full")

    # --- Diff Mode ---

    def _toggle_diff_mode(self) -> None:
        """Toggle between normal mode and diff comparison mode."""
        self._diff_mode = not self._diff_mode
        self._selected_turns.clear()

        if self._detail_container:
            self._detail_container.clear()

        if self._diff_mode:
            with self._detail_container:
                ui.label("Select two turns to compare.").style(
                    "color: #999; font-size: 0.85em;"
                )

        # Re-render timeline with appropriate buttons
        self._refresh_timeline()

    def _build_diff_select_button(self, entry: TurnInfo) -> None:
        """Build a select/deselect button for diff mode."""
        is_selected = entry.turn in self._selected_turns

        def make_toggle_handler(t: int):
            def handler():
                if t in self._selected_turns:
                    self._selected_turns.remove(t)
                elif len(self._selected_turns) < 2:
                    self._selected_turns.append(t)
                    if len(self._selected_turns) == 2:
                        self._show_diff()
                # Re-render timeline to update selection state
                self._refresh_timeline()

            return handler

        ui.button(
            icon="check_circle" if is_selected else "radio_button_unchecked",
            on_click=make_toggle_handler(entry.turn),
        ).props("flat dense round").style(
            f"color: {INFO_COLOR if is_selected else '#666'};"
        )

    def _show_diff(self) -> None:
        """Show the unified diff between two selected turns."""
        if len(self._selected_turns) != 2:
            return

        turn_a, turn_b = sorted(self._selected_turns)

        if self._detail_container:
            self._detail_container.clear()

        try:
            diff_text = git_save.diff_turns(self.save_path, turn_a, turn_b)
        except ValueError as e:
            with self._detail_container:
                ui.label(f"Error: {e}").style(f"color: {ERROR_COLOR};")
            return

        with self._detail_container:
            ui.label(f"Diff: Turn {turn_a} vs Turn {turn_b}").style(
                f"color: {INFO_COLOR}; font-weight: bold; font-size: 0.95em; "
                "margin-bottom: 8px;"
            )

            if not diff_text.strip():
                ui.label("No differences found.").style("color: #888;")
                return

            # Parse diff to identify changed files
            changed_files: set[str] = set()
            for line in diff_text.splitlines():
                if line.startswith("diff --git"):
                    parts = line.split()
                    if len(parts) >= 4:
                        changed_files.add(parts[3].removeprefix("b/"))

            if changed_files:
                ui.label(f"Changed files: {', '.join(sorted(changed_files))}").style(
                    "color: #999; font-size: 0.8em; margin-bottom: 8px;"
                )

            # Render diff with color-coded lines
            html_lines: list[str] = []
            for line in diff_text.splitlines():
                escaped = html_lib.escape(line)
                if line.startswith("+") and not line.startswith("+++"):
                    html_lines.append(
                        f'<div style="color: {SUCCESS_COLOR}; font-family: monospace; '
                        f"font-size: 0.8em; background: #1a3a1a; "
                        f'padding: 1px 4px;">{escaped}</div>'
                    )
                elif line.startswith("-") and not line.startswith("---"):
                    html_lines.append(
                        f'<div style="color: {ERROR_COLOR}; font-family: monospace; '
                        f"font-size: 0.8em; background: #3a1a1a; "
                        f'padding: 1px 4px;">{escaped}</div>'
                    )
                elif line.startswith("@@"):
                    html_lines.append(
                        f'<div style="color: {INFO_COLOR}; font-family: monospace; '
                        f'font-size: 0.8em; padding: 1px 4px;">{escaped}</div>'
                    )
                else:
                    html_lines.append(
                        f'<div style="color: #999; font-family: monospace; '
                        f'font-size: 0.8em; padding: 1px 4px;">{escaped}</div>'
                    )

            ui.html("\n".join(html_lines)).style(
                "max-height: 400px; overflow-y: auto; "
                "background: #1a1a1a; border: 1px solid #333; "
                "border-radius: 4px; padding: 8px;"
            )

    # --- Restore ---

    def _confirm_restore(self, target_turn: int) -> None:
        """Show a confirmation dialog before restoring to a past turn."""
        steps = self.current_turn - target_turn
        if steps <= 0:
            ui.notify(
                "Cannot restore to the current or a future turn.",
                type="warning",
            )
            return

        with ui.dialog() as dialog, ui.card():
            ui.label(f"Restore to Turn {target_turn}?").style(
                "color: #ccc; font-weight: bold;"
            )
            ui.label(
                f"This will undo {steps} turn{'s' if steps != 1 else ''}. "
                f"This cannot be reversed."
            ).style(f"color: {WARNING_ACCENT_COLOR}; font-size: 0.9em;")
            ui.label("Tip: Use Fork first to keep a copy of the current state.").style(
                "color: #888; font-size: 0.8em;"
            )

            with ui.row().classes("justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def confirm():
                    dialog.close()
                    try:
                        new_turn = git_save.undo(self.save_path, steps)
                        self.current_turn = new_turn
                        ui.notify(
                            f"Restored to turn {new_turn}.",
                            type="positive",
                        )
                        if self.on_restore:
                            self.on_restore(steps)
                        self.close()
                    except ValueError as e:
                        ui.notify(f"Restore failed: {e}", type="negative")

                ui.button("Restore", on_click=confirm, icon="restore").props(
                    "flat"
                ).style(f"color: {WARNING_ACCENT_COLOR};")
        dialog.open()
