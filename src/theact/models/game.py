"""Game metadata and loaded game aggregate models."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from theact.models.chapter import Chapter, ChapterSummary
from theact.models.character import Character
from theact.models.conversation import ConversationEntry
from theact.models.memory import CharacterMemory
from theact.models.state import GameState
from theact.models.world import World


class GameMeta(BaseModel):
    """Top-level game definition metadata. Loaded from game.yaml."""

    model_config = ConfigDict(extra="forbid")

    id: str  # URL-safe slug, e.g. "lost-island"
    title: str  # Display name, e.g. "The Lost Island"
    description: str  # One-sentence pitch
    characters: list[str]  # Character file stems, e.g. ["maya", "joaquin"]
    chapters: list[str]  # Chapter file stems in order, e.g. ["01-the-crash", ...]


class LoadedGame(BaseModel):
    """A fully loaded game with all data resolved. Not persisted -- constructed in memory."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    meta: GameMeta
    world: World
    characters: dict[str, Character]  # keyed by character file stem
    chapters: dict[str, Chapter]  # keyed by chapter id
    state: GameState
    conversation: list[ConversationEntry]
    memories: dict[str, CharacterMemory]  # keyed by character file stem
    chapter_summaries: list[ChapterSummary]
    save_path: Path  # Absolute path to save directory
