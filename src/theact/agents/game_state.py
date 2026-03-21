"""Game state agent: checks chapter progress and beat completion."""

from __future__ import annotations

import logging

from theact.engine.context import build_game_state_messages
from theact.engine.types import GameStateResult
from theact.llm.config import GAME_STATE_CONFIG, LLMConfig
from theact.llm.inference import complete_structured
from theact.llm.parsing import YAMLParseError
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame

logger = logging.getLogger(__name__)


async def run_game_state(
    game: LoadedGame,
    turn_entries: list[ConversationEntry],
    llm_config: LLMConfig,
) -> GameStateResult:
    """Run the game state check agent.

    Non-streaming (runs silently in background).
    Returns chapter completion status and any new beats hit.
    """
    messages = build_game_state_messages(game, turn_entries)

    if not messages:
        # No current chapter found -- nothing to check
        return GameStateResult(beats_hit=[], completed=False)

    try:
        result = await complete_structured(
            messages=messages,
            llm_config=llm_config,
            agent_config=GAME_STATE_CONFIG,
            yaml_hint=("chapter_complete: false\\nreason: ...\\nnew_beats:\\n  - ..."),
        )
        data = result.data
    except YAMLParseError as e:
        logger.warning("Game state YAML parse failed: %s", e)
        return GameStateResult(beats_hit=[], completed=False)

    return GameStateResult(
        beats_hit=data.get("new_beats") or [],
        completed=bool(data.get("chapter_complete", False)),
        reasoning=data.get("reason"),
    )
