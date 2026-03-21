"""Pure command logic — no UI imports, no rendering.

Every function returns a CommandResult. The caller (CLI or web)
decides how to render it.
"""

from __future__ import annotations

from theact.commands.types import CommandResult
from theact.io.save_manager import load_save
from theact.models.game import LoadedGame
from theact.versioning import git_save

# Canonical command table — single source of truth for both CLI and web.
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
    "save-as": {"args": "<name>", "desc": "Fork the current save to a new name"},
}


def cmd_help() -> CommandResult:
    """Return help rows for all slash commands."""
    rows = [
        {"command": f"/{name}", "args": info["args"], "desc": info["desc"]}
        for name, info in COMMANDS.items()
    ]
    return CommandResult(success=True, title="Commands", rows=rows)


def cmd_status(game: LoadedGame) -> CommandResult:
    """Return game status: chapter, turn, beats, flags."""
    chapter_id = game.state.current_chapter
    chapter = game.chapters.get(chapter_id)

    lines: list[str] = []
    if chapter:
        beats_total = len(chapter.beats)
        beats_done = len(game.state.beats_hit)
        lines.append(f"Chapter: {chapter.title} ({chapter.id})")
        lines.append(f"Turn: {game.state.turn}")
        lines.append(f"Beats: {beats_done}/{beats_total}")
    else:
        lines.append(f"Chapter: {chapter_id} (not found)")
        lines.append(f"Turn: {game.state.turn}")

    if game.state.flags:
        lines.append(f"Flags: {game.state.flags}")

    return CommandResult(success=True, message="\n".join(lines))


def cmd_save_info(game: LoadedGame) -> CommandResult:
    """Return save metadata."""
    lines = [
        f"Save: {game.save_path.name}",
        f"Game: {game.meta.title}",
        f"Player: {game.state.player_name}",
        f"Path: {game.save_path}",
    ]
    return CommandResult(success=True, message="\n".join(lines))


def cmd_history(game: LoadedGame) -> CommandResult:
    """Return turn history rows from git log."""
    history = git_save.get_history(game.save_path)
    if not history:
        return CommandResult(success=True, message="No turn history yet.")

    rows = [
        {
            "turn": str(entry.turn),
            "summary": entry.message,
            "time": entry.timestamp,
        }
        for entry in history
    ]
    return CommandResult(success=True, title="Turn History", rows=rows)


def cmd_memory(game: LoadedGame, args: list[str]) -> CommandResult:
    """Return character memory. With no args, list characters."""
    if not args:
        lines = ["Characters:"]
        for key, char in game.characters.items():
            has_memory = key in game.memories
            marker = " (has memory)" if has_memory else ""
            lines.append(f"  - {char.name}{marker}")
        return CommandResult(success=True, message="\n".join(lines))

    # Find character by fuzzy match (case-insensitive, partial)
    query = " ".join(args).lower()
    match = None
    for key, char in game.characters.items():
        if query in char.name.lower() or query in key.lower():
            match = key
            break

    if match is None:
        names = [game.characters[k].name for k in game.characters]
        return CommandResult(
            success=False,
            message=f"Unknown character. Available: {', '.join(names)}",
        )

    if match not in game.memories:
        return CommandResult(
            success=True,
            message=f"{game.characters[match].name} has no memories yet.",
        )

    memory = game.memories[match]
    lines = [f"{memory.character} -- Memory", "", f"Summary: {memory.summary}"]
    if memory.key_facts:
        lines.append("Key facts:")
        for fact in memory.key_facts:
            lines.append(f"  - {fact}")
    return CommandResult(success=True, message="\n".join(lines))


def cmd_conversation(game: LoadedGame, args: list[str]) -> CommandResult:
    """Return the last N conversation entries as text lines."""
    count = 5
    if args:
        try:
            count = int(args[0])
            if count < 1:
                raise ValueError
        except ValueError:
            return CommandResult(
                success=False,
                message="Usage: /conversation [N] where N is a positive integer.",
            )

    entries = game.conversation[-count:]
    if not entries:
        return CommandResult(success=True, message="No conversation yet.")

    lines: list[str] = []
    for entry in entries:
        if entry.role == "narrator":
            text = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
            lines.append(f"Narrator: {text}")
        elif entry.role == "player":
            lines.append(f"{game.state.player_name}: {entry.content}")
        elif entry.role == "character":
            name = entry.character or "?"
            text = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
            lines.append(f"{name}: {text}")
    return CommandResult(success=True, message="\n".join(lines))


def cmd_undo(game: LoadedGame, args: list[str]) -> CommandResult:
    """Undo N turns. Returns the reloaded game in ``data``."""
    steps = 1
    if args:
        try:
            steps = int(args[0])
            if steps < 1:
                raise ValueError
        except ValueError:
            return CommandResult(
                success=False,
                message="Usage: /undo [N] where N is a positive integer.",
            )

    try:
        new_turn = git_save.undo(game.save_path, steps)
        reloaded = load_save(game.save_path.name, game.save_path.parent)
        return CommandResult(
            success=True,
            message=f"Undone {steps} turn(s). Now at turn {new_turn}.",
            data=reloaded,
        )
    except ValueError as e:
        return CommandResult(success=False, message=f"Cannot undo: {e}")


def cmd_save_as(game: LoadedGame, args: list[str]) -> CommandResult:
    """Fork the current save to a new name."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: /save-as <name>",
        )

    new_name = args[0]
    try:
        new_path = git_save.save_as(game.save_path, new_name)
        return CommandResult(
            success=True,
            message=f"Save forked to '{new_name}' at {new_path}",
        )
    except FileExistsError:
        return CommandResult(
            success=False,
            message=f"A save named '{new_name}' already exists.",
        )
    except FileNotFoundError as e:
        return CommandResult(success=False, message=f"Cannot fork: {e}")
