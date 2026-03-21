"""Summarizer agent: chapter summaries and rolling summary updates."""

from __future__ import annotations

from theact.engine.context import build_rolling_summary_messages, build_summary_messages
from theact.llm.config import SUMMARIZER_CONFIG, LLMConfig
from theact.llm.inference import complete
from theact.models.chapter import Chapter
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame


async def run_chapter_summary(
    game: LoadedGame,
    chapter: Chapter,
    llm_config: LLMConfig,
) -> str:
    """Summarize a completed chapter in 2-3 sentences.

    Non-streaming, plain text output.
    """
    messages = build_summary_messages(game, chapter)

    result = await complete(
        messages=messages,
        llm_config=llm_config,
        agent_config=SUMMARIZER_CONFIG,
    )

    return result.content.strip()


async def run_rolling_summary(
    existing_summary: str,
    old_entries: list[ConversationEntry],
    llm_config: LLMConfig,
) -> str:
    """Incrementally update the rolling summary.

    Merges the existing summary with old conversation entries that
    are being trimmed from the verbatim window. Non-streaming, plain text.
    """
    messages = build_rolling_summary_messages(existing_summary, old_entries)

    result = await complete(
        messages=messages,
        llm_config=llm_config,
        agent_config=SUMMARIZER_CONFIG,
    )

    return result.content.strip()
