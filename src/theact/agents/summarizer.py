"""Summarizer agent: chapter summaries and rolling summary updates."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from theact.engine.context import build_rolling_summary_messages, build_summary_messages
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.llm.config import SUMMARIZER_CONFIG, LLMConfig
from theact.llm.errors import ParseFailureType
from theact.llm.inference import complete
from theact.llm.tokens import estimate_tokens
from theact.models.chapter import Chapter
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame


async def run_chapter_summary(
    game: LoadedGame,
    chapter: Chapter,
    llm_config: LLMConfig,
    call_log: LLMCallLog | None = None,
    turn: int = 0,
) -> str:
    """Summarize a completed chapter in 2-3 sentences.

    Non-streaming, plain text output.
    """
    messages = build_summary_messages(game, chapter)
    t0 = time.monotonic()

    result = await complete(
        messages=messages,
        llm_config=llm_config,
        agent_config=SUMMARIZER_CONFIG,
    )

    if call_log:
        latency = int((time.monotonic() - t0) * 1000)
        call_log.log(
            LLMCallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent="summarizer",
                turn=turn,
                prompt_tokens=result.prompt_tokens
                or estimate_tokens(" ".join(m.get("content", "") for m in messages)),
                thinking_tokens=estimate_tokens(result.thinking),
                content_tokens=result.completion_tokens
                or estimate_tokens(result.content),
                latency_ms=latency,
                finish_reason=result.finish_reason,
                parse_result=ParseFailureType.success.value,
                parse_attempts=1,
                retry_count=0,
                temperature=SUMMARIZER_CONFIG.temperature
                or llm_config.default_temperature,
                max_tokens=SUMMARIZER_CONFIG.max_tokens
                or llm_config.default_max_tokens,
            )
        )

    return result.content.strip()


async def run_rolling_summary(
    existing_summary: str,
    old_entries: list[ConversationEntry],
    llm_config: LLMConfig,
    call_log: LLMCallLog | None = None,
    turn: int = 0,
) -> str:
    """Incrementally update the rolling summary.

    Merges the existing summary with old conversation entries that
    are being trimmed from the verbatim window. Non-streaming, plain text.
    """
    messages = build_rolling_summary_messages(existing_summary, old_entries)
    t0 = time.monotonic()

    result = await complete(
        messages=messages,
        llm_config=llm_config,
        agent_config=SUMMARIZER_CONFIG,
    )

    if call_log:
        latency = int((time.monotonic() - t0) * 1000)
        call_log.log(
            LLMCallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent="summarizer",
                turn=turn,
                prompt_tokens=result.prompt_tokens
                or estimate_tokens(" ".join(m.get("content", "") for m in messages)),
                thinking_tokens=estimate_tokens(result.thinking),
                content_tokens=result.completion_tokens
                or estimate_tokens(result.content),
                latency_ms=latency,
                finish_reason=result.finish_reason,
                parse_result=ParseFailureType.success.value,
                parse_attempts=1,
                retry_count=0,
                temperature=SUMMARIZER_CONFIG.temperature
                or llm_config.default_temperature,
                max_tokens=SUMMARIZER_CONFIG.max_tokens
                or llm_config.default_max_tokens,
            )
        )

    return result.content.strip()
