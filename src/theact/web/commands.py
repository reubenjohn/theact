"""Slash command handling for the web UI.

Reuses the CLI's parse_command() for parsing, but renders output
to the web UI instead of Rich Console.
"""

from __future__ import annotations

import html as html_lib

from nicegui import ui

from theact.cli.commands import parse_command
from theact.io.save_manager import load_save
from theact.models.game import LoadedGame
from theact.versioning import git_save
from theact.web.components import show_system_message

# Re-export for convenience.
__all__ = ["parse_command"]

# Help text for web display.
COMMANDS_HELP = """
<table style="width: 100%; border-collapse: collapse;">
<tr><th style="text-align: left; padding: 4px; border-bottom: 1px solid #555;">
Command</th>
<th style="text-align: left; padding: 4px; border-bottom: 1px solid #555;">
Args</th>
<th style="text-align: left; padding: 4px; border-bottom: 1px solid #555;">
Description</th></tr>
<tr><td style="padding: 4px;">/help</td><td></td>
<td>Show this help message</td></tr>
<tr><td style="padding: 4px;">/quit</td><td></td>
<td>Return to main menu</td></tr>
<tr><td style="padding: 4px;">/undo</td><td>[N]</td>
<td>Undo last N turns (default: 1)</td></tr>
<tr><td style="padding: 4px;">/history</td><td></td>
<td>Show turn history</td></tr>
<tr><td style="padding: 4px;">/save</td><td></td>
<td>Show current save info</td></tr>
<tr><td style="padding: 4px;">/status</td><td></td>
<td>Show game status</td></tr>
<tr><td style="padding: 4px;">/memory</td><td>[character]</td>
<td>Show character memory</td></tr>
<tr><td style="padding: 4px;">/think</td><td>[on|off]</td>
<td>Toggle thinking display</td></tr>
<tr><td style="padding: 4px;">/retry</td><td></td>
<td>Undo last turn and replay same input</td></tr>
<tr><td style="padding: 4px;">/conversation</td><td>[N]</td>
<td>Show last N conversation entries</td></tr>
</table>
"""


def cmd_help_web(chat_area: ui.element) -> None:
    """Display command reference as a system message."""
    show_system_message(chat_area, COMMANDS_HELP)


def cmd_status_web(chat_area: ui.element, game: LoadedGame) -> None:
    """Display game status as a system message."""
    chapter_id = game.state.current_chapter
    chapter = game.chapters.get(chapter_id)

    lines = []
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

    show_system_message(chat_area, html_lib.escape("\n".join(lines)))


def cmd_save_web(chat_area: ui.element, game: LoadedGame) -> None:
    """Display save info as a system message."""
    lines = [
        f"Save: {game.save_path.name}",
        f"Game: {game.meta.title}",
        f"Player: {game.state.player_name}",
        f"Path: {game.save_path}",
    ]
    show_system_message(chat_area, html_lib.escape("\n".join(lines)))


def cmd_history_web(chat_area: ui.element, game: LoadedGame) -> None:
    """Display turn history as a system message."""
    history = git_save.get_history(game.save_path)
    if not history:
        show_system_message(chat_area, "No turn history yet.")
        return

    rows = ""
    for entry in history:
        rows += (
            f"<tr><td style='padding: 4px;'>{entry.turn}</td>"
            f"<td style='padding: 4px;'>{html_lib.escape(entry.message)}</td>"
            f"<td style='padding: 4px;'>{html_lib.escape(entry.timestamp)}</td></tr>"
        )

    table_html = (
        "<table style='width: 100%; border-collapse: collapse;'>"
        "<tr>"
        "<th style='text-align: left; padding: 4px; border-bottom: 1px solid #555;'>"
        "Turn</th>"
        "<th style='text-align: left; padding: 4px; border-bottom: 1px solid #555;'>"
        "Summary</th>"
        "<th style='text-align: left; padding: 4px; border-bottom: 1px solid #555;'>"
        "Time</th>"
        "</tr>"
        f"{rows}</table>"
    )
    show_system_message(chat_area, table_html)


def cmd_memory_web(chat_area: ui.element, game: LoadedGame, args: list[str]) -> None:
    """Display character memory as a system message."""
    if not args:
        lines = ["Characters:"]
        for key, char in game.characters.items():
            has_memory = key in game.memories
            marker = " (has memory)" if has_memory else ""
            lines.append(f"  - {char.name}{marker}")
        show_system_message(chat_area, html_lib.escape("\n".join(lines)))
        return

    # Fuzzy match character
    query = " ".join(args).lower()
    match = None
    for key, char in game.characters.items():
        if query in char.name.lower() or query in key.lower():
            match = key
            break

    if match is None:
        names = [game.characters[k].name for k in game.characters]
        show_system_message(
            chat_area,
            html_lib.escape(f"Unknown character. Available: {', '.join(names)}"),
        )
        return

    if match not in game.memories:
        show_system_message(
            chat_area,
            html_lib.escape(f"{game.characters[match].name} has no memories yet."),
        )
        return

    memory = game.memories[match]
    lines = [f"{memory.character} -- Memory", "", f"Summary: {memory.summary}"]
    if memory.key_facts:
        lines.append("Key facts:")
        for fact in memory.key_facts:
            lines.append(f"  - {fact}")
    show_system_message(chat_area, html_lib.escape("\n".join(lines)))


def cmd_conversation_web(
    chat_area: ui.element, game: LoadedGame, args: list[str]
) -> None:
    """Show the last N conversation entries as a system message."""
    count = 5
    if args:
        try:
            count = int(args[0])
            if count < 1:
                raise ValueError
        except ValueError:
            ui.notify(
                "Usage: /conversation [N] where N is a positive integer.",
                type="warning",
            )
            return

    entries = game.conversation[-count:]
    if not entries:
        show_system_message(chat_area, "No conversation yet.")
        return

    lines = []
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
    show_system_message(chat_area, html_lib.escape("\n".join(lines)))


def cmd_undo_web(
    game: LoadedGame,
    args: list[str],
) -> tuple[LoadedGame | None, str]:
    """Undo N turns. Returns (reloaded_game, message).

    If undo fails, returns (None, error_message).
    """
    steps = 1
    if args:
        try:
            steps = int(args[0])
            if steps < 1:
                raise ValueError
        except ValueError:
            return None, "Usage: /undo [N] where N is a positive integer."

    try:
        new_turn = git_save.undo(game.save_path, steps)
        reloaded = load_save(game.save_path.name, game.save_path.parent)
        return reloaded, f"Undone {steps} turn(s). Now at turn {new_turn}."
    except ValueError as e:
        return None, f"Cannot undo: {e}"
