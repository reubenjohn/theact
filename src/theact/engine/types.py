"""Runtime result types for the turn engine.

These are plain dataclasses, NOT Pydantic models -- they represent
ephemeral turn results, not persisted game data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NarratorOutput:
    """Parsed output from the narrator agent."""

    narration: str
    responding_characters: list[str]  # ordered list of character ids
    mood: str  # e.g. "tense", "calm", "urgent"


@dataclass
class CharacterResponse:
    """A single character's response."""

    character: str  # character name
    response: str  # the dialogue/action text
    thinking: str | None = None  # optional chain-of-thought from the model


@dataclass
class MemoryDiff:
    """Changes applied to a character's memory this turn."""

    character: str
    old_summary: str
    new_summary: str
    old_facts: list[str] = field(default_factory=list)
    new_facts: list[str] = field(default_factory=list)
    raw_fact_count: int = 0  # before truncation, for overflow detection


@dataclass
class GameStateResult:
    """Result of the game state check."""

    beats_hit: list[str] = field(default_factory=list)
    completed: bool = False
    reasoning: str | None = None


@dataclass
class TurnResult:
    """Complete result of a single turn, returned to the caller."""

    turn: int
    narrator: NarratorOutput
    characters: list[CharacterResponse]
    memory_diffs: list[MemoryDiff]
    game_state: GameStateResult | None = None
    chapter_advanced: bool = False
    new_chapter: str | None = None
    summary_updated: bool = False
