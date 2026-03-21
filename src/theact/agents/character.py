"""Character agent: streams a single character's in-character response."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from theact.engine.context import build_character_messages
from theact.engine.types import CharacterResponse, NarratorOutput
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.llm.config import AgentLLMConfig, CHARACTER_CONFIG, LLMConfig
from theact.llm.errors import ParseFailureType
from theact.llm.inference import stream
from theact.llm.tokens import estimate_tokens
from theact.models.character import Character
from theact.models.game import LoadedGame
from theact.models.memory import CharacterMemory

logger = logging.getLogger(__name__)

StreamCallback = Callable[[str], Awaitable[None]]


async def run_character(
    game: LoadedGame,
    character: Character,
    memory: CharacterMemory | None,
    player_input: str,
    narrator_output: NarratorOutput,
    prior_responses: list[CharacterResponse],
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
    call_log: LLMCallLog | None = None,
    turn: int = 0,
) -> CharacterResponse:
    """Run a character agent.

    Streams plain text tokens for live display.
    Returns the character's dialogue/action response.
    """
    messages = build_character_messages(
        game=game,
        character=character,
        memory=memory,
        player_input=player_input,
        narrator_output=narrator_output,
        prior_responses=prior_responses,
        llm_config=llm_config,
    )

    content_parts: list[str] = []
    thinking_parts: list[str] = []
    finish_reason = "stop"
    retry_count = 0
    t0 = time.monotonic()

    async for chunk in await stream(
        messages=messages,
        llm_config=llm_config,
        agent_config=CHARACTER_CONFIG,
    ):
        if chunk.content:
            content_parts.append(chunk.content)
            if on_token:
                await on_token(chunk.content)
        if chunk.thinking:
            thinking_parts.append(chunk.thinking)
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason

    content = "".join(content_parts)
    thinking = "".join(thinking_parts)

    # Retry once if response is too short (empty or near-empty)
    if len(content.strip()) < 10:
        logger.warning(
            "Character %s returned near-empty response (%d chars), retrying",
            character.name,
            len(content.strip()),
        )
        retry_count = 1
        bumped_temp = (
            CHARACTER_CONFIG.temperature or llm_config.default_temperature
        ) + 0.1
        retry_config = AgentLLMConfig(
            temperature=bumped_temp,
            max_tokens=CHARACTER_CONFIG.max_tokens,
            structured=False,
        )

        content_parts = []
        thinking_parts = []
        finish_reason = "stop"

        async for chunk in await stream(
            messages=messages,
            llm_config=llm_config,
            agent_config=retry_config,
        ):
            if chunk.content:
                content_parts.append(chunk.content)
                if on_token:
                    await on_token(chunk.content)
            if chunk.thinking:
                thinking_parts.append(chunk.thinking)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason

        content = "".join(content_parts)
        thinking = "".join(thinking_parts)

        # If still empty after retry, use fallback
        if len(content.strip()) < 10:
            content = f"*{character.name} remains silent.*"

    if call_log:
        latency = int((time.monotonic() - t0) * 1000)
        # Derive a short char id from the character name for the agent label
        char_id = character.name.lower().replace(" ", "_")
        call_log.log(
            LLMCallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=f"character:{char_id}",
                turn=turn,
                prompt_tokens=estimate_tokens(
                    " ".join(m.get("content", "") for m in messages)
                ),
                thinking_tokens=estimate_tokens(thinking),
                content_tokens=estimate_tokens(content),
                latency_ms=latency,
                finish_reason=finish_reason,
                parse_result=ParseFailureType.success.value,
                parse_attempts=1 + retry_count,
                retry_count=retry_count,
                temperature=CHARACTER_CONFIG.temperature
                or llm_config.default_temperature,
                max_tokens=CHARACTER_CONFIG.max_tokens or llm_config.default_max_tokens,
            )
        )

    return CharacterResponse(
        character=character.name,
        response=content.strip(),
        thinking=thinking or None,
    )
