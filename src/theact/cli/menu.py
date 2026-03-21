"""Game management menus: list, create, load, delete."""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from theact.cli.styles import ERROR_STYLE, STATUS_STYLE
from theact.io.save_manager import list_games, list_saves
from theact.models.game import GameMeta


def show_game_list(console: Console) -> list[GameMeta]:
    """Display available games as a numbered table. Returns the list."""
    games = list_games()
    if not games:
        console.print("No games found in games/.", style=ERROR_STYLE)
        return []
    table = Table(title="Available Games")
    table.add_column("#", style="bold")
    table.add_column("Title")
    table.add_column("Description")
    for i, game in enumerate(games, 1):
        table.add_row(str(i), game.title, game.description)
    console.print(table)
    return games


def show_save_list(console: Console) -> list[dict]:
    """Display existing saves as a numbered table. Returns the list."""
    saves = list_saves()
    if not saves:
        console.print("No saves found.", style=STATUS_STYLE)
        return []
    table = Table(title="Saved Games")
    table.add_column("#", style="bold")
    table.add_column("Save ID")
    table.add_column("Game")
    table.add_column("Turn")
    table.add_column("Last Played")
    for i, save in enumerate(saves, 1):
        # Format timestamp for display
        modified = save.get("last_modified", 0)
        if isinstance(modified, (int, float)) and modified > 0:
            ts = datetime.fromtimestamp(modified, tz=timezone.utc)
            time_str = ts.strftime("%Y-%m-%d %H:%M")
        else:
            time_str = "unknown"
        table.add_row(
            str(i),
            save["id"],
            save["game_title"],
            str(save["turn"]),
            time_str,
        )
    console.print(table)
    return saves


def prompt_choice(console: Console, items: list, prompt: str = "Select") -> int | None:
    """Prompt user to pick a numbered item.

    Returns 0-based index or None on cancel (empty input or 'q').
    """
    while True:
        try:
            raw = console.input(f"\n{prompt} (number, or q to cancel): ")
        except EOFError:
            return None
        raw = raw.strip()
        if not raw or raw.lower() == "q":
            return None
        try:
            choice = int(raw)
            if 1 <= choice <= len(items):
                return choice - 1
            console.print(
                f"Please enter a number between 1 and {len(items)}.",
                style=ERROR_STYLE,
            )
        except ValueError:
            console.print("Please enter a number.", style=ERROR_STYLE)


def prompt_text(console: Console, prompt: str, default: str = "") -> str:
    """Prompt for free-form text input. Returns stripped string."""
    suffix = f" [{default}]" if default else ""
    try:
        raw = console.input(f"{prompt}{suffix}: ")
    except EOFError:
        return default
    raw = raw.strip()
    return raw if raw else default


def confirm(console: Console, message: str) -> bool:
    """Yes/no confirmation. Returns True if yes."""
    try:
        raw = console.input(f"{message} (y/n): ")
    except EOFError:
        return False
    return raw.strip().lower() in ("y", "yes")


def slugify(text: str) -> str:
    """Convert a free-form name to a URL-safe slug.

    Lowercase, replace spaces/special chars with hyphens,
    strip leading/trailing hyphens, collapse multiple hyphens.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "save"


def delete_save_dir(save_path) -> None:
    """Remove a save directory from disk."""
    shutil.rmtree(save_path)
