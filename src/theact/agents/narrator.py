"""Narrator agent: streams narration and parses structured YAML output."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from theact.engine.context import build_narrator_messages
from theact.engine.types import NarratorOutput
from theact.llm.config import NARRATOR_CONFIG, LLMConfig
from theact.llm.inference import stream_structured
from theact.llm.parsing import YAMLParseError
from theact.models.game import LoadedGame

logger = logging.getLogger(__name__)

StreamCallback = Callable[[str], Awaitable[None]]


async def run_narrator(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
) -> NarratorOutput:
    """Run the narrator agent.

    Streams tokens for live display, then parses structured YAML output
    containing narration, responding_characters, and mood.
    """
    messages = build_narrator_messages(game, player_input, llm_config)

    try:
        stream_iter, result_future = await stream_structured(
            messages=messages,
            llm_config=llm_config,
            agent_config=NARRATOR_CONFIG,
            yaml_hint=(
                "narration: |\\n  ...\\n"
                "responding_characters:\\n  - ...\\n"
                "mood: tense|calm|urgent|mysterious|humorous|dramatic|melancholic"
            ),
        )

        async for chunk in stream_iter:
            if on_token and chunk.content:
                await on_token(chunk.content)

        result = await result_future
        data = result.data

    except YAMLParseError as e:
        logger.warning("Narrator YAML parse failed after retries: %s", e)
        # Fall back to using raw content as narration
        raw = e.raw_content if hasattr(e, "raw_content") else ""
        return NarratorOutput(
            narration=raw.strip() or "(The narrator is silent.)",
            responding_characters=[],
            mood="neutral",
        )

    return NarratorOutput(
        narration=data.get("narration", "").strip(),
        responding_characters=data.get("responding_characters") or [],
        mood=data.get("mood", "neutral") or "neutral",
    )
