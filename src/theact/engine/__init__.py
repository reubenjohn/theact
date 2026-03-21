"""Turn engine: orchestrates a single game turn."""

from theact.engine.types import (
    CharacterResponse,
    GameStateResult,
    MemoryDiff,
    NarratorOutput,
    TurnResult,
)

__all__ = [
    "CharacterResponse",
    "GameStateResult",
    "MemoryDiff",
    "NarratorOutput",
    "TurnResult",
    "build_character_messages",
    "build_game_state_messages",
    "build_memory_messages",
    "build_narrator_messages",
    "build_rolling_summary_messages",
    "build_summary_messages",
    "format_chapter_context",
    "format_conversation",
    "get_recent_conversation",
    "run_turn",
]

# Context and turn imports are deferred to avoid a circular dependency:
# engine.context -> agents.prompts -> agents.__init__ -> agents.character -> engine.context
_CONTEXT_NAMES = {
    "build_character_messages",
    "build_game_state_messages",
    "build_memory_messages",
    "build_narrator_messages",
    "build_rolling_summary_messages",
    "build_summary_messages",
    "format_chapter_context",
    "format_conversation",
    "get_recent_conversation",
}


def __getattr__(name: str):
    if name in _CONTEXT_NAMES:
        from theact.engine import context

        return getattr(context, name)
    if name == "run_turn":
        from theact.engine.turn import run_turn

        return run_turn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
