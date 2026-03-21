"""Game state model."""

from pydantic import BaseModel, ConfigDict


class GameState(BaseModel):
    """Mutable game state. Written to state.yaml. Updated every turn."""

    model_config = ConfigDict(extra="forbid")

    player_name: str
    current_chapter: str  # Chapter id
    turn: int  # Monotonically increasing turn counter
    beats_hit: list[str]  # Beat phrases from current chapter that have occurred
    flags: dict[str, str]  # Arbitrary key-value pairs set by agents
    chapter_history: list[str]  # List of completed chapter ids
    rolling_summary: str = ""  # Incremental summary of expired conversation turns.
