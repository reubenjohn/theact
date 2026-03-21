"""Memory update agent: updates a character's memory after a turn."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from theact.engine.context import build_memory_messages
from theact.engine.types import MemoryDiff
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.llm.config import MEMORY_UPDATE_CONFIG, LLMConfig
from theact.llm.errors import ParseFailureType
from theact.llm.inference import complete_structured
from theact.llm.parsing import YAMLParseError
from theact.llm.tokens import estimate_tokens
from theact.models.character import Character
from theact.models.conversation import ConversationEntry
from theact.models.memory import CharacterMemory

logger = logging.getLogger(__name__)


async def run_memory_update(
    character: Character,
    memory: CharacterMemory | None,
    turn_entries: list[ConversationEntry],
    llm_config: LLMConfig,
    call_log: LLMCallLog | None = None,
    turn: int = 0,
) -> MemoryDiff:
    """Run the memory update agent for a single character.

    Non-streaming (runs silently in background).
    Returns a MemoryDiff with old and new summary/facts.
    """
    messages = build_memory_messages(character, memory, turn_entries)
    t0 = time.monotonic()

    old_summary = memory.summary if memory else ""
    old_facts = list(memory.key_facts) if memory else []

    try:
        result = await complete_structured(
            messages=messages,
            llm_config=llm_config,
            agent_config=MEMORY_UPDATE_CONFIG,
            yaml_hint=(
                "summary: |\\n  ...\\n"
                "add:\\n  - ...\\n"
                "remove:\\n  - ...\\n"
                "update:\\n  - old: ...\\n    new: ..."
            ),
        )
        data = result.data
    except YAMLParseError as e:
        logger.warning("Memory update YAML parse failed for %s: %s", character.name, e)
        if call_log:
            latency = int((time.monotonic() - t0) * 1000)
            failure_type = getattr(e, "failure_type", ParseFailureType.wrong_schema)
            char_id = character.name.lower().replace(" ", "_")
            call_log.log(
                LLMCallRecord(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    agent=f"memory:{char_id}",
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
                    temperature=MEMORY_UPDATE_CONFIG.temperature
                    or llm_config.default_temperature,
                    max_tokens=MEMORY_UPDATE_CONFIG.max_tokens
                    or llm_config.default_max_tokens,
                )
            )
        return MemoryDiff(
            character=character.name,
            old_summary=old_summary,
            new_summary=old_summary,
            old_facts=old_facts,
            new_facts=old_facts,
        )

    if call_log:
        latency = int((time.monotonic() - t0) * 1000)
        char_id = character.name.lower().replace(" ", "_")
        call_log.log(
            LLMCallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent=f"memory:{char_id}",
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
                temperature=MEMORY_UPDATE_CONFIG.temperature
                or llm_config.default_temperature,
                max_tokens=MEMORY_UPDATE_CONFIG.max_tokens
                or llm_config.default_max_tokens,
            )
        )

    new_summary = data.get("summary", old_summary) or old_summary

    # Apply add/remove/update operations to build new facts list
    new_facts = list(old_facts)

    for fact in data.get("remove", []) or []:
        if fact in new_facts:
            new_facts.remove(fact)

    for entry in data.get("update", []) or []:
        if isinstance(entry, dict) and "old" in entry and "new" in entry:
            try:
                idx = new_facts.index(entry["old"])
                new_facts[idx] = entry["new"]
            except ValueError:
                # Old fact not found; treat as an add
                new_facts.append(entry["new"])

    for fact in data.get("add", []) or []:
        new_facts.append(fact)

    # Enforce max 10 key facts
    new_facts = new_facts[:10]

    return MemoryDiff(
        character=character.name,
        old_summary=old_summary,
        new_summary=new_summary.strip(),
        old_facts=old_facts,
        new_facts=new_facts,
    )
