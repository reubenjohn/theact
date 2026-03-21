"""Shared types for command results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandResult:
    """Uniform result from any slash command.

    Both CLI and web command handlers return this. The renderer
    (CLI console or web UI) decides how to display it.
    """

    success: bool
    message: str = ""
    data: Any = None  # e.g., reloaded LoadedGame for /undo
    rows: list[dict[str, str]] = field(default_factory=list)  # tabular data
    title: str = ""  # optional heading
