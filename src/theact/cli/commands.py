"""Slash command parsing and handlers for the CLI.

Each command is a thin wrapper: it calls the shared logic in
``theact.commands.logic`` and renders the result using Rich.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from theact.cli.styles import COMMAND_OUTPUT_STYLE, ERROR_STYLE, STATUS_STYLE
from theact.commands.logic import COMMANDS
from theact.commands.logic import cmd_conversation as _cmd_conversation
from theact.commands.logic import cmd_help as _cmd_help
from theact.commands.logic import cmd_history as _cmd_history
from theact.commands.logic import cmd_memory as _cmd_memory
from theact.commands.logic import cmd_save_as as _cmd_save_as
from theact.commands.logic import cmd_save_info as _cmd_save_info
from theact.commands.logic import cmd_status as _cmd_status
from theact.commands.logic import cmd_undo as _cmd_undo
from theact.models.game import LoadedGame

# Re-export COMMANDS so existing imports from theact.cli.commands still work.
__all__ = ["COMMANDS", "parse_command"]


def parse_command(raw_input: str) -> tuple[str, list[str]] | None:
    """Parse a slash command. Returns (name, args) or None if not a command.

    Examples:
        "/undo"        -> ("undo", [])
        "/undo 3"      -> ("undo", ["3"])
        "/memory maya"  -> ("memory", ["maya"])
        "hello"        -> None
    """
    stripped = raw_input.strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped[1:].split()
    if not parts:
        return None
    return parts[0].lower(), parts[1:]


def cmd_help(console: Console) -> None:
    """Display command reference as a Rich table."""
    result = _cmd_help()
    table = Table(title=result.title, show_header=True)
    table.add_column("Command", style="bold")
    table.add_column("Args")
    table.add_column("Description")
    for row in result.rows:
        table.add_row(row["command"], row["args"], row["desc"])
    console.print(table)


def cmd_undo(console: Console, game: LoadedGame, args: list[str]) -> LoadedGame:
    """Undo N turns. Returns the reloaded game.

    Prints error messages for invalid args or when undo exceeds history.
    """
    result = _cmd_undo(game, args)
    if result.success:
        console.print(result.message, style=STATUS_STYLE)
        return result.data
    else:
        console.print(result.message, style=ERROR_STYLE)
        return game


def cmd_history(console: Console, game: LoadedGame) -> None:
    """Display turn history from git log."""
    result = _cmd_history(game)
    if not result.rows:
        console.print(result.message, style=STATUS_STYLE)
        return
    table = Table(title=result.title)
    table.add_column("Turn", style="bold")
    table.add_column("Summary")
    table.add_column("Time")
    for row in result.rows:
        table.add_row(row["turn"], row["summary"], row["time"])
    console.print(table)


def cmd_save(console: Console, game: LoadedGame) -> None:
    """Display save info."""
    result = _cmd_save_info(game)
    for line in result.message.splitlines():
        console.print(f"  {line}", style=COMMAND_OUTPUT_STYLE)


def cmd_status(console: Console, game: LoadedGame) -> None:
    """Display game status: chapter, turn, beats, flags."""
    result = _cmd_status(game)
    for line in result.message.splitlines():
        console.print(f"  {line}", style=COMMAND_OUTPUT_STYLE)


def cmd_memory(console: Console, game: LoadedGame, args: list[str]) -> None:
    """Display character memory. With no args, lists characters."""
    result = _cmd_memory(game, args)
    style = ERROR_STYLE if not result.success else COMMAND_OUTPUT_STYLE
    for line in result.message.splitlines():
        console.print(f"  {line}", style=style)


def cmd_think(console: Console, args: list[str], current: bool) -> bool:
    """Toggle or set thinking display. Returns new state.

    This command stays in the CLI because it has UI-specific state (returns bool).
    """
    if not args:
        state = "on" if current else "off"
        console.print(f"Thinking display is {state}.", style=STATUS_STYLE)
        return current

    arg = args[0].lower()
    if arg == "on":
        console.print("Thinking display enabled.", style=STATUS_STYLE)
        return True
    elif arg == "off":
        console.print("Thinking display disabled.", style=STATUS_STYLE)
        return False
    else:
        console.print("Usage: /think [on|off]", style=ERROR_STYLE)
        return current


def cmd_conversation(console: Console, game: LoadedGame, args: list[str]) -> None:
    """Show the last N conversation entries."""
    result = _cmd_conversation(game, args)
    if not result.success:
        console.print(result.message, style=ERROR_STYLE)
        return
    if result.message in ("No conversation yet.",):
        console.print(result.message, style=STATUS_STYLE)
        return
    console.print()
    for line in result.message.splitlines():
        console.print(f"  {line}", style=COMMAND_OUTPUT_STYLE)
    console.print()


def cmd_save_as(console: Console, game: LoadedGame, args: list[str]) -> None:
    """Fork the current save to a new name."""
    result = _cmd_save_as(game, args)
    style = STATUS_STYLE if result.success else ERROR_STYLE
    console.print(result.message, style=style)
