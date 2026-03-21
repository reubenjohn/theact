"""Web command rendering — thin layer over shared logic.

These functions are kept for backward compatibility. New code should
use CommandRouter, which calls commands/logic.py directly and renders
via html_utils.render_result().
"""

from __future__ import annotations

from nicegui import ui

from theact.commands import logic
from theact.models.game import LoadedGame
from theact.web.components.html_utils import render_result


def cmd_help_web(chat_area: ui.element) -> None:
    """Display command reference as a system message."""
    result = logic.cmd_help()
    render_result(chat_area, result)


def cmd_status_web(chat_area: ui.element, game: LoadedGame) -> None:
    """Display game status as a system message."""
    result = logic.cmd_status(game)
    render_result(chat_area, result)


def cmd_save_web(chat_area: ui.element, game: LoadedGame) -> None:
    """Display save info as a system message."""
    result = logic.cmd_save_info(game)
    render_result(chat_area, result)


def cmd_history_web(chat_area: ui.element, game: LoadedGame) -> None:
    """Display turn history as a system message."""
    result = logic.cmd_history(game)
    render_result(chat_area, result)


def cmd_memory_web(chat_area: ui.element, game: LoadedGame, args: list[str]) -> None:
    """Display character memory as a system message."""
    result = logic.cmd_memory(game, args)
    render_result(chat_area, result)


def cmd_conversation_web(
    chat_area: ui.element, game: LoadedGame, args: list[str]
) -> None:
    """Show the last N conversation entries as a system message."""
    result = logic.cmd_conversation(game, args)
    render_result(chat_area, result)


def cmd_undo_web(
    game: LoadedGame,
    args: list[str],
) -> tuple[LoadedGame | None, str]:
    """Undo N turns. Returns (reloaded_game, message).

    If undo fails, returns (None, error_message).
    Kept for backward compatibility with existing tests.
    """
    result = logic.cmd_undo(game, args)
    if result.success:
        return result.data, result.message
    return None, result.message


def cmd_save_as_web(game: LoadedGame, args: list[str]) -> None:
    """Fork the current save to a new name. Uses ui.notify for feedback."""
    result = logic.cmd_save_as(game, args)
    if result.success:
        ui.notify(result.message, type="positive")
    else:
        ui.notify(result.message, type="warning")
