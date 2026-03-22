"""Narrator agent: streams narration and parses structured YAML output."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from theact.engine.context import build_narrator_messages
from theact.engine.types import NarratorOutput
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.llm.config import NARRATOR_CONFIG, LLMConfig
from theact.llm.errors import ParseFailureType
from theact.llm.inference import complete_structured, stream_structured
from theact.llm.parsing import YAMLParseError
from theact.llm.tokens import estimate_tokens
from theact.models.game import LoadedGame

logger = logging.getLogger(__name__)

StreamCallback = Callable[[str, bool], Awaitable[None]]

VALID_MOODS = frozenset(
    {"tense", "calm", "urgent", "mysterious", "humorous", "dramatic", "melancholic"}
)

# Common synonyms / small-model paraphrases → canonical mood
_MOOD_SYNONYMS: dict[str, str] = {
    "sad": "melancholic",
    "sorrowful": "melancholic",
    "somber": "melancholic",
    "grim": "melancholic",
    "dark": "tense",
    "scary": "tense",
    "suspenseful": "tense",
    "anxious": "tense",
    "nervous": "tense",
    "eerie": "mysterious",
    "strange": "mysterious",
    "curious": "mysterious",
    "weird": "mysterious",
    "funny": "humorous",
    "comedic": "humorous",
    "lighthearted": "humorous",
    "peaceful": "calm",
    "relaxed": "calm",
    "serene": "calm",
    "quiet": "calm",
    "neutral": "calm",
    "intense": "dramatic",
    "epic": "dramatic",
    "exciting": "dramatic",
    "danger": "urgent",
    "desperate": "urgent",
    "critical": "urgent",
    "panicked": "urgent",
}


def _normalize_mood(raw: str) -> str:
    """Map a model-returned mood to a valid canonical mood."""
    if raw in VALID_MOODS:
        return raw
    if raw in _MOOD_SYNONYMS:
        mapped = _MOOD_SYNONYMS[raw]
        logger.info("Normalized mood %r → %r", raw, mapped)
        return mapped
    logger.warning("Unrecognized mood %r, defaulting to 'calm'", raw)
    return "calm"


async def run_narrator(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
    call_log: LLMCallLog | None = None,
    turn: int = 0,
) -> NarratorOutput:
    """Run the narrator agent.

    Streams tokens for live display, then parses structured YAML output
    containing narration, responding_characters, and mood.
    """
    messages = build_narrator_messages(game, player_input, llm_config)
    t0 = time.monotonic()

    yaml_hint = (
        "responding_characters:\\n  - ...\\n"
        "mood: tense|calm|urgent|mysterious|humorous|dramatic|melancholic\\n"
        "narration: |\\n  ..."
    )
    raw_content = ""
    retried = False

    try:
        stream_iter, result_future = await stream_structured(
            messages=messages,
            llm_config=llm_config,
            agent_config=NARRATOR_CONFIG,
            yaml_hint=yaml_hint,
        )

        async for chunk in stream_iter:
            if on_token and chunk.thinking:
                await on_token(chunk.thinking, True)
            if on_token and chunk.content:
                await on_token(chunk.content, False)

        result = await result_future
        data = result.data

    except YAMLParseError as e:
        # Streaming parse failed — retry once with non-streaming
        raw_content = e.raw_content if hasattr(e, "raw_content") else ""
        logger.warning("Narrator streaming parse failed, retrying non-streaming: %s", e)
        retried = True
        try:
            result = await complete_structured(
                messages=messages,
                llm_config=llm_config,
                agent_config=NARRATOR_CONFIG,
                yaml_hint=yaml_hint,
            )
            data = result.data
        except YAMLParseError as e2:
            # Both attempts failed — return fallback
            logger.warning("Narrator non-streaming retry also failed: %s", e2)
            raw_content = e2.raw_content if hasattr(e2, "raw_content") else raw_content
            if call_log:
                latency = int((time.monotonic() - t0) * 1000)
                failure_type = getattr(
                    e2, "failure_type", ParseFailureType.wrong_schema
                )
                call_log.log(
                    LLMCallRecord(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        agent="narrator",
                        turn=turn,
                        prompt_tokens=estimate_tokens(
                            " ".join(m.get("content", "") for m in messages)
                        ),
                        thinking_tokens=0,
                        content_tokens=estimate_tokens(raw_content),
                        latency_ms=latency,
                        finish_reason="error",
                        parse_result=failure_type.value,
                        parse_attempts=2,
                        retry_count=1,
                        temperature=NARRATOR_CONFIG.temperature
                        or llm_config.default_temperature,
                        max_tokens=NARRATOR_CONFIG.max_tokens
                        or llm_config.default_max_tokens,
                    )
                )
            return NarratorOutput(
                narration=raw_content.strip() or "(The narrator is silent.)",
                responding_characters=[],
                mood="calm",
            )

    if call_log:
        latency = int((time.monotonic() - t0) * 1000)
        retry_count = max(0, result.attempts - 1) + (1 if retried else 0)
        call_log.log(
            LLMCallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent="narrator",
                turn=turn,
                prompt_tokens=result.prompt_tokens
                or estimate_tokens(" ".join(m.get("content", "") for m in messages)),
                thinking_tokens=estimate_tokens(result.thinking),
                content_tokens=result.completion_tokens
                or estimate_tokens(result.raw_content),
                latency_ms=latency,
                finish_reason=result.finish_reason,
                parse_result=ParseFailureType.success.value,
                parse_attempts=result.attempts + (1 if retried else 0),
                retry_count=retry_count,
                temperature=NARRATOR_CONFIG.temperature
                or llm_config.default_temperature,
                max_tokens=NARRATOR_CONFIG.max_tokens or llm_config.default_max_tokens,
            )
        )

    raw_mood = (data.get("mood") or "calm").strip().lower()
    mood = _normalize_mood(raw_mood)

    return NarratorOutput(
        narration=data.get("narration", "").strip(),
        responding_characters=data.get("responding_characters") or [],
        mood=mood,
    )
