"""Game state agent: checks chapter progress and beat completion."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from theact.engine.context import build_game_state_messages
from theact.engine.types import GameStateResult
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.llm.config import GAME_STATE_CONFIG, LLMConfig
from theact.llm.errors import ParseFailureType
from theact.llm.inference import complete_structured
from theact.llm.parsing import YAMLParseError
from theact.llm.tokens import estimate_tokens
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame

logger = logging.getLogger(__name__)


async def run_game_state(
    game: LoadedGame,
    turn_entries: list[ConversationEntry],
    llm_config: LLMConfig,
    call_log: LLMCallLog | None = None,
    turn: int = 0,
) -> GameStateResult:
    """Run the game state check agent.

    Non-streaming (runs silently in background).
    Returns chapter completion status and any new beats hit.
    """
    messages = build_game_state_messages(game, turn_entries)

    if not messages:
        # No current chapter found -- nothing to check
        return GameStateResult(beats_hit=[], completed=False)

    t0 = time.monotonic()

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
        if call_log:
            latency = int((time.monotonic() - t0) * 1000)
            failure_type = getattr(e, "failure_type", ParseFailureType.wrong_schema)
            call_log.log(
                LLMCallRecord(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    agent="game_state",
                    turn=turn,
                    prompt_tokens=estimate_tokens(
                        " ".join(m.get("content", "") for m in messages)
                    ),
                    thinking_tokens=0,
                    content_tokens=estimate_tokens(
                        e.raw_content if hasattr(e, "raw_content") else ""
                    ),
                    latency_ms=latency,
                    finish_reason="error",
                    parse_result=failure_type.value,
                    parse_attempts=1,
                    retry_count=0,
                    temperature=GAME_STATE_CONFIG.temperature
                    or llm_config.default_temperature,
                    max_tokens=GAME_STATE_CONFIG.max_tokens
                    or llm_config.default_max_tokens,
                )
            )
        return GameStateResult(beats_hit=[], completed=False)

    if call_log:
        latency = int((time.monotonic() - t0) * 1000)
        call_log.log(
            LLMCallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent="game_state",
                turn=turn,
                prompt_tokens=result.prompt_tokens
                or estimate_tokens(" ".join(m.get("content", "") for m in messages)),
                thinking_tokens=estimate_tokens(result.thinking),
                content_tokens=result.completion_tokens
                or estimate_tokens(result.raw_content),
                latency_ms=latency,
                finish_reason=result.finish_reason,
                parse_result=ParseFailureType.success.value,
                parse_attempts=result.attempts,
                retry_count=max(0, result.attempts - 1),
                temperature=GAME_STATE_CONFIG.temperature
                or llm_config.default_temperature,
                max_tokens=GAME_STATE_CONFIG.max_tokens
                or llm_config.default_max_tokens,
            )
        )

    return GameStateResult(
        beats_hit=data.get("new_beats") or [],
        completed=bool(data.get("chapter_complete", False)),
        reasoning=data.get("reason"),
    )
