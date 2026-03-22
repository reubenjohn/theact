"""Memory update agent: updates a character's memory after a turn."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from theact.agents.prompts import MAX_KEY_FACTS
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


def _find_fact(needle: str, facts: list[str]) -> int | None:
    """Find the index of *needle* in *facts*, tolerating small-model paraphrasing.

    Tries: exact → case-insensitive → best word-overlap (≥60%).
    Returns the index or None.
    """
    if not needle or not facts:
        return None
    # 1. Exact
    if needle in facts:
        return facts.index(needle)
    # 2. Case-insensitive
    lower = needle.lower()
    for i, f in enumerate(facts):
        if f.lower() == lower:
            return i
    # 3. Word overlap
    needle_words = {w for w in lower.split() if len(w) > 2}
    if not needle_words:
        return None
    best_idx: int | None = None
    best_score = 0.0
    for i, f in enumerate(facts):
        fact_words = {w for w in f.lower().split() if len(w) > 2}
        if not fact_words:
            continue
        overlap = len(needle_words & fact_words)
        shorter = min(len(needle_words), len(fact_words))
        score = overlap / shorter
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx if best_score >= 0.6 else None


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
        idx = _find_fact(fact, new_facts)
        if idx is not None:
            new_facts.pop(idx)

    for entry in data.get("update", []) or []:
        if isinstance(entry, dict) and "old" in entry and "new" in entry:
            idx = _find_fact(entry["old"], new_facts)
            if idx is not None:
                new_facts[idx] = entry["new"]
            else:
                # Old fact not found; treat as an add
                new_facts.append(entry["new"])

    for fact in data.get("add", []) or []:
        new_facts.append(fact)

    # Enforce max key facts limit
    new_facts = new_facts[:MAX_KEY_FACTS]

    return MemoryDiff(
        character=character.name,
        old_summary=old_summary,
        new_summary=new_summary.strip(),
        old_facts=old_facts,
        new_facts=new_facts,
    )
