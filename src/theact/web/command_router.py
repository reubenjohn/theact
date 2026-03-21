"""Command dispatch for the web UI.

Routes slash commands to shared logic and renders results.
Handles web-specific commands (think, quit) locally.
"""

from __future__ import annotations

import logging

from nicegui import ui

from theact.commands import logic
from theact.commands.types import CommandResult
from theact.web.components.html_utils import render_result
from theact.web.state import GameSessionState

logger = logging.getLogger(__name__)


class CommandRouter:
    """Dispatches slash commands and renders results to the chat area."""

    def __init__(self, state: GameSessionState, chat_area: ui.element) -> None:
        self._state = state
        self._chat_area = chat_area

    def execute(self, cmd: str, args: list[str]) -> CommandResult | None:
        """Execute a command and render output. Returns result.

        'think', 'quit', and 'retry' are NOT handled here — the session
        manages them since they affect session-level state.
        """
        handler = self._COMMANDS.get(cmd)
        if handler is None:
            ui.notify(
                f"Unknown command: /{cmd}. Type /help for available commands.",
                type="warning",
            )
            return CommandResult(success=False, message=f"Unknown command: /{cmd}")
        return handler(self, args)

    def _cmd_help(self, args: list[str]) -> CommandResult:
        result = logic.cmd_help()
        render_result(self._chat_area, result)
        return result

    def _cmd_status(self, args: list[str]) -> CommandResult:
        result = logic.cmd_status(self._state.game)
        render_result(self._chat_area, result)
        return result

    def _cmd_save(self, args: list[str]) -> CommandResult:
        result = logic.cmd_save_info(self._state.game)
        render_result(self._chat_area, result)
        return result

    def _cmd_history(self, args: list[str]) -> CommandResult:
        result = logic.cmd_history(self._state.game)
        render_result(self._chat_area, result)
        return result

    def _cmd_memory(self, args: list[str]) -> CommandResult:
        result = logic.cmd_memory(self._state.game, args)
        render_result(self._chat_area, result)
        return result

    def _cmd_conversation(self, args: list[str]) -> CommandResult:
        result = logic.cmd_conversation(self._state.game, args)
        render_result(self._chat_area, result)
        return result

    def _cmd_undo(self, args: list[str]) -> CommandResult:
        result = logic.cmd_undo(self._state.game, args)
        if result.success and result.data:
            self._state.game = result.data
            self._state.notify()
        render_result(self._chat_area, result)
        return result

    def _cmd_save_as(self, args: list[str]) -> CommandResult:
        result = logic.cmd_save_as(self._state.game, args)
        if result.success:
            ui.notify(result.message, type="positive")
        else:
            ui.notify(result.message, type="warning")
        return result

    _COMMANDS = {
        "help": _cmd_help,
        "status": _cmd_status,
        "save": _cmd_save,
        "history": _cmd_history,
        "memory": _cmd_memory,
        "conversation": _cmd_conversation,
        "undo": _cmd_undo,
        "save-as": _cmd_save_as,
    }
