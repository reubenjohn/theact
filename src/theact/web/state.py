"""Shared game session state.

All web UI components (session, sidebar, toolbar, history) read from
this object. It is updated by the session orchestrator after turns
and commands. Components should NEVER mutate state directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from theact.llm.config import LLMConfig
from theact.models.game import LoadedGame


@dataclass
class GameSessionState:
    """Observable state for a gameplay session."""

    game: LoadedGame
    llm_config: LLMConfig
    show_thinking: bool = True
    processing: bool = False
    last_player_input: str = ""
    debug_mode: bool = False

    # Listeners called when state changes
    _listeners: list[Callable[[], None]] = field(default_factory=list, repr=False)

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Register a callback to be notified on state changes."""
        self._listeners.append(callback)

    def notify(self) -> None:
        """Notify all listeners that state has changed."""
        for cb in self._listeners:
            cb()

    def reload_game(self) -> None:
        """Reload game from disk and notify listeners."""
        from theact.io.save_manager import load_save

        self.game = load_save(self.game.save_path.name, self.game.save_path.parent)
        self.notify()

    @property
    def character_list(self) -> list[str]:
        """Ordered list of character stems."""
        return list(self.game.characters.keys())
