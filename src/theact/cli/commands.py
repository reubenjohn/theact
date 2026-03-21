"""Slash command parsing and handlers for the CLI."""

from __future__ import annotations

from rich.console import Console
from rich.style import Style
from rich.table import Table

from theact.cli.styles import COMMAND_OUTPUT_STYLE, ERROR_STYLE, STATUS_STYLE
from theact.io.save_manager import load_save
from theact.models.game import LoadedGame
from theact.versioning import git_save

COMMANDS = {
    "help": {"args": "", "desc": "Show this help message"},
    "quit": {"args": "", "desc": "Exit to main menu"},
    "undo": {"args": "[N]", "desc": "Undo last N turns (default: 1)"},
    "history": {"args": "", "desc": "Show turn history"},
    "save": {"args": "", "desc": "Show current save info"},
    "status": {"args": "", "desc": "Show game status"},
    "memory": {"args": "[character]", "desc": "Show character memory"},
    "think": {"args": "[on|off]", "desc": "Toggle thinking display"},
    "retry": {"args": "", "desc": "Undo last turn and replay same input"},
    "conversation": {"args": "[N]", "desc": "Show last N conversation entries"},
}


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
    """Display command reference."""
    table = Table(title="Commands", show_header=True)
    table.add_column("Command", style="bold")
    table.add_column("Args")
    table.add_column("Description")
    for name, info in COMMANDS.items():
        table.add_row(f"/{name}", info["args"], info["desc"])
    console.print(table)


def cmd_undo(console: Console, game: LoadedGame, args: list[str]) -> LoadedGame:
    """Undo N turns. Returns the reloaded game.

    Prints error messages for invalid args or when undo exceeds history.
    """
    steps = 1
    if args:
        try:
            steps = int(args[0])
            if steps < 1:
                raise ValueError
        except ValueError:
            console.print(
                "Usage: /undo [N] where N is a positive integer.",
                style=ERROR_STYLE,
            )
            return game

    try:
        new_turn = git_save.undo(game.save_path, steps)
        game = load_save(game.save_path.name, game.save_path.parent)
        console.print(
            f"Undone {steps} turn(s). Now at turn {new_turn}.",
            style=STATUS_STYLE,
        )
        return game
    except ValueError as e:
        console.print(f"Cannot undo: {e}", style=ERROR_STYLE)
        return game


def cmd_history(console: Console, game: LoadedGame) -> None:
    """Display turn history from git log."""
    history = git_save.get_history(game.save_path)
    if not history:
        console.print("No turn history yet.", style=STATUS_STYLE)
        return
    table = Table(title="Turn History")
    table.add_column("Turn", style="bold")
    table.add_column("Summary")
    table.add_column("Time")
    for entry in history:
        table.add_row(str(entry.turn), entry.message, entry.timestamp)
    console.print(table)


def cmd_save(console: Console, game: LoadedGame) -> None:
    """Display save info."""
    console.print(f"  Save:    {game.save_path.name}", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Game:    {game.meta.title}", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Player:  {game.state.player_name}", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Path:    {game.save_path}", style=COMMAND_OUTPUT_STYLE)


def cmd_status(console: Console, game: LoadedGame) -> None:
    """Display game status: chapter, turn, beats, flags."""
    chapter_id = game.state.current_chapter
    chapter = game.chapters.get(chapter_id)
    if not chapter:
        console.print(
            f"  Chapter: {chapter_id} (not found)", style=COMMAND_OUTPUT_STYLE
        )
        console.print(f"  Turn:    {game.state.turn}", style=COMMAND_OUTPUT_STYLE)
        return

    beats_total = len(chapter.beats)
    beats_done = len(game.state.beats_hit)

    console.print(
        f"  Chapter: {chapter.title} ({chapter.id})", style=COMMAND_OUTPUT_STYLE
    )
    console.print(f"  Turn:    {game.state.turn}", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Beats:   {beats_done}/{beats_total}", style=COMMAND_OUTPUT_STYLE)
    if game.state.flags:
        console.print(f"  Flags:   {game.state.flags}", style=COMMAND_OUTPUT_STYLE)


def cmd_memory(console: Console, game: LoadedGame, args: list[str]) -> None:
    """Display character memory. With no args, lists characters."""
    if not args:
        console.print("Characters:", style=COMMAND_OUTPUT_STYLE)
        for key, char in game.characters.items():
            has_memory = key in game.memories
            marker = " (has memory)" if has_memory else ""
            console.print(f"  - {char.name}{marker}", style=COMMAND_OUTPUT_STYLE)
        return

    # Find character by fuzzy match (case-insensitive, partial)
    query = " ".join(args).lower()
    match = None
    for key, char in game.characters.items():
        if query in char.name.lower() or query in key.lower():
            match = key
            break

    if match is None:
        names = [game.characters[k].name for k in game.characters]
        console.print(
            f"Unknown character. Available: {', '.join(names)}",
            style=ERROR_STYLE,
        )
        return

    if match not in game.memories:
        console.print(
            f"{game.characters[match].name} has no memories yet.",
            style=STATUS_STYLE,
        )
        return

    memory = game.memories[match]
    console.print(f"\n  {memory.character} — Memory", style=Style(bold=True))
    console.print(f"\n  Summary: {memory.summary}", style=COMMAND_OUTPUT_STYLE)
    if memory.key_facts:
        console.print("  Key facts:", style=COMMAND_OUTPUT_STYLE)
        for fact in memory.key_facts:
            console.print(f"    - {fact}", style=COMMAND_OUTPUT_STYLE)
    console.print()


def cmd_think(console: Console, args: list[str], current: bool) -> bool:
    """Toggle or set thinking display. Returns new state."""
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
    count = 5
    if args:
        try:
            count = int(args[0])
            if count < 1:
                raise ValueError
        except ValueError:
            console.print(
                "Usage: /conversation [N] where N is a positive integer.",
                style=ERROR_STYLE,
            )
            return

    entries = game.conversation[-count:]
    if not entries:
        console.print("No conversation yet.", style=STATUS_STYLE)
        return

    console.print()
    for entry in entries:
        if entry.role == "narrator":
            text = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
            console.print(f"  Narrator: {text}", style=COMMAND_OUTPUT_STYLE)
        elif entry.role == "player":
            console.print(
                f"  {game.state.player_name}: {entry.content}",
                style=COMMAND_OUTPUT_STYLE,
            )
        elif entry.role == "character":
            name = entry.character or "?"
            text = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
            console.print(f"  {name}: {text}", style=COMMAND_OUTPUT_STYLE)
    console.print()
