"""Gameplay toolbar with quick-action buttons.

Provides clickable icon buttons for common actions that currently
require slash commands. Each button calls existing command functions
from commands/logic.py or versioning/git_save.py.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from nicegui import ui

from theact.web.components.dialogs import number_input_dialog, text_input_dialog


class GameplayToolbar:
    """Row of icon buttons for common gameplay actions.

    Args:
        on_undo: Async callback for undo action. Receives number of steps.
        on_retry: Async callback for retry action.
        on_save_as: Async callback for save-as action. Receives new save name.
        on_history: Callback to open the history panel.
        is_processing: Reads from ``GameSessionState.processing`` (the shared
            observable state from Step 00) instead of a lambda.
    """

    def __init__(
        self,
        on_undo: Callable[[int], Awaitable[None]],
        on_retry: Callable[[], Awaitable[None]],
        on_save_as: Callable[[str], Awaitable[None]],
        on_history: Callable[[], None],
        is_processing: Callable[[], bool],
    ) -> None:
        self._on_undo = on_undo
        self._on_retry = on_retry
        self._on_save_as = on_save_as
        self._on_history = on_history
        self._is_processing = is_processing

        # UI references (set during build)
        self._undo_btn: ui.button | None = None
        self._retry_btn: ui.button | None = None
        self._save_as_btn: ui.button | None = None
        self._history_btn: ui.button | None = None

    def build(self, container: ui.element) -> None:
        """Build the toolbar row inside the given container."""
        with container:
            with (
                ui.row()
                .classes("w-full items-center px-2 py-1 gap-1")
                .style("border-bottom: 1px solid #333;")
            ):
                self._undo_btn = (
                    ui.button(icon="undo", on_click=self._show_undo_dialog)
                    .props('flat dense data-testid="toolbar-undo"')
                    .tooltip("Undo last turn")
                    .style("color: #999;")
                )
                self._retry_btn = (
                    ui.button(icon="refresh", on_click=self._handle_retry)
                    .props('flat dense data-testid="toolbar-retry"')
                    .tooltip("Retry last turn")
                    .style("color: #999;")
                )
                self._save_as_btn = (
                    ui.button(icon="fork_right", on_click=self._show_save_as_dialog)
                    .props('flat dense data-testid="toolbar-save-as"')
                    .tooltip("Fork save")
                    .style("color: #999;")
                )
                self._history_btn = (
                    ui.button(icon="history", on_click=self._handle_history)
                    .props('flat dense data-testid="toolbar-history"')
                    .tooltip("Turn history")
                    .style("color: #999;")
                )

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all toolbar buttons."""
        for btn in [
            self._undo_btn,
            self._retry_btn,
            self._save_as_btn,
            self._history_btn,
        ]:
            if btn is not None:
                if enabled:
                    btn.enable()
                else:
                    btn.disable()

    def _show_undo_dialog(self) -> None:
        """Show undo confirmation dialog with step count input."""
        if self._is_processing():
            return
        number_input_dialog(
            title="Undo Turns",
            message="How many turns to undo?",
            on_submit=self._on_undo,
            label="Steps",
            default=1,
            min_val=1,
            max_val=100,
            submit_text="Undo",
            submit_color="#ff9800",
        )

    async def _handle_retry(self) -> None:
        """Invoke the retry callback directly (no confirmation needed)."""
        if self._is_processing():
            return
        await self._on_retry()

    def _show_save_as_dialog(self) -> None:
        """Show save-as dialog with name input."""
        if self._is_processing():
            return
        text_input_dialog(
            title="Fork Save",
            message="Enter a name for the new save:",
            on_submit=self._on_save_as,
            label="Save name",
            placeholder="my-save-fork",
            submit_text="Create",
            submit_color="#69f0ae",
        )

    def _handle_history(self) -> None:
        """Invoke the history callback."""
        if self._is_processing():
            return
        self._on_history()
