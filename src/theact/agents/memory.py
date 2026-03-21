"""Memory update agent: updates a character's memory after a turn."""

from __future__ import annotations

import logging

from theact.engine.context import build_memory_messages
from theact.engine.types import MemoryDiff
from theact.llm.config import MEMORY_UPDATE_CONFIG, LLMConfig
from theact.llm.inference import complete_structured
from theact.llm.parsing import YAMLParseError
from theact.models.character import Character
from theact.models.conversation import ConversationEntry
from theact.models.memory import CharacterMemory

logger = logging.getLogger(__name__)


async def run_memory_update(
    character: Character,
    memory: CharacterMemory | None,
    turn_entries: list[ConversationEntry],
    llm_config: LLMConfig,
) -> MemoryDiff:
    """Run the memory update agent for a single character.

    Non-streaming (runs silently in background).
    Returns a MemoryDiff with old and new summary/facts.
    """
    messages = build_memory_messages(character, memory, turn_entries)

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
        return MemoryDiff(
            character=character.name,
            old_summary=old_summary,
            new_summary=old_summary,
            old_facts=old_facts,
            new_facts=old_facts,
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
