"""Context assembly for agent prompts.

Builds the messages array (system prompt + conversation history) for each
agent type.  Handles token-budgeted conversation trimming to stay within
the model's context window.

This is the most critical code in the system -- it decides what each agent
sees.  Every token wasted here is a token the 7B model cannot use for
reasoning or output.
"""

from __future__ import annotations

from theact.agents.prompts import (
    CHARACTER_SYSTEM,
    CHAPTER_SUMMARY_SYSTEM,
    GAME_STATE_SYSTEM,
    MEMORY_UPDATE_SYSTEM,
    NARRATOR_SYSTEM,
    ROLLING_SUMMARY_SYSTEM,
)
from theact.engine.types import CharacterResponse, NarratorOutput
from theact.llm.config import (
    CHARACTER_CONFIG,
    LLMConfig,
    NARRATOR_CONFIG,
)
from theact.llm.tokens import tokens_remaining
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame
from theact.models.memory import CharacterMemory

Message = dict[str, str]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_recent_conversation(
    conversation: list[ConversationEntry],
    max_turns: int = 4,
) -> list[ConversationEntry]:
    """Get the last *max_turns* turns of conversation (all entries within those turns)."""
    if not conversation:
        return []
    turns_seen: list[int] = []
    for entry in reversed(conversation):
        if entry.turn not in turns_seen:
            turns_seen.append(entry.turn)
        if len(turns_seen) >= max_turns:
            break
    cutoff_turn = turns_seen[-1] if turns_seen else 0
    return [e for e in conversation if e.turn >= cutoff_turn]


def format_conversation(entries: list[ConversationEntry]) -> str:
    """Format conversation entries into a compact readable text block."""
    lines: list[str] = []
    for e in entries:
        if e.role == "narrator":
            lines.append(f"[Narrator]: {e.content}")
        elif e.role == "player":
            lines.append(f"[Player]: {e.content}")
        elif e.role == "character":
            lines.append(f"[{e.character}]: {e.content}")
    return "\n".join(lines)


def format_chapter_context(game: LoadedGame) -> str:
    """Format chapter progression: completed summaries, current chapter with beat status, upcoming titles."""
    parts: list[str] = []

    # Completed chapters (2-3 line summaries)
    if game.chapter_summaries:
        parts.append("COMPLETED CHAPTERS:")
        for cs in game.chapter_summaries:
            parts.append(f"- {cs.title}: {cs.summary}")

    # Current chapter (full definition with beat checklist)
    current = game.chapters.get(game.state.current_chapter)
    if current:
        beats_status: list[str] = []
        for beat in current.beats:
            hit = "x" if beat in game.state.beats_hit else " "
            beats_status.append(f"  [{hit}] {beat}")
        parts.append(f"\nCURRENT CHAPTER: {current.title}")
        parts.append(f"Goal: {current.summary}")
        parts.append("Beats:")
        parts.extend(beats_status)
        parts.append(f"Complete when: {current.completion}")

    # Upcoming chapters (titles only)
    chapter_order = game.meta.chapters
    current_idx = (
        chapter_order.index(game.state.current_chapter)
        if game.state.current_chapter in chapter_order
        else -1
    )
    upcoming = chapter_order[current_idx + 1 :] if current_idx >= 0 else []
    if upcoming:
        titles = [game.chapters[cid].title for cid in upcoming if cid in game.chapters]
        if titles:
            parts.append(f"\nUPCOMING: {', '.join(titles)}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------


def build_narrator_messages(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
) -> list[Message]:
    """Build the message list for the narrator agent."""
    chapter_context = format_chapter_context(game)
    recent = get_recent_conversation(game.conversation)
    recent_text = format_conversation(recent)

    # Active characters for this chapter (show ID + name so the model knows the mapping)
    current_chapter = game.chapters.get(game.state.current_chapter)
    active_chars = (
        current_chapter.characters if current_chapter else list(game.characters.keys())
    )
    char_names = ", ".join(
        f"{cid} ({game.characters[cid].name})"
        for cid in active_chars
        if cid in game.characters
    )

    system = NARRATOR_SYSTEM.format(
        world_setting=game.world.setting,
        world_tone=game.world.tone,
        world_rules=game.world.rules,
        chapter_context=chapter_context,
        active_characters=char_names,
    )

    messages: list[Message] = [{"role": "system", "content": system}]

    # Merge rolling summary, recent conversation, and player input into a
    # SINGLE user message.  Some APIs merge or behave unpredictably with
    # multiple consecutive same-role messages, so we consolidate here.
    user_parts: list[str] = []

    if game.state.rolling_summary:
        user_parts.append(f"Story so far: {game.state.rolling_summary}")

    if recent_text:
        user_parts.append(f"Recent conversation:\n{recent_text}")

    # Opening scene guidance
    if not game.conversation and game.state.turn == 0:
        user_parts.append(
            "This is the opening scene. Set the stage and introduce the setting."
        )

    # Chapter transition signal
    if game.state.chapter_just_advanced:
        user_parts.append(
            "The previous chapter is complete. Begin the new chapter "
            "with a transition scene."
        )

    user_parts.append(f"Player says: {player_input}")

    messages.append(
        {
            "role": "user",
            "content": "\n\n".join(user_parts),
        }
    )

    # Token budget check -- trim recent conversation if needed
    budget = tokens_remaining(
        messages,
        llm_config.context_limit,
        NARRATOR_CONFIG.max_tokens or llm_config.default_max_tokens,
    )
    if budget < 0:
        # Retry with fewer turns
        recent = get_recent_conversation(game.conversation, max_turns=2)
        recent_text = format_conversation(recent)
        user_parts_trimmed: list[str] = []
        if game.state.rolling_summary:
            user_parts_trimmed.append(f"Story so far: {game.state.rolling_summary}")
        if recent_text:
            user_parts_trimmed.append(f"Recent:\n{recent_text}")
        if game.state.chapter_just_advanced:
            user_parts_trimmed.append(
                "The previous chapter is complete. Begin the new chapter "
                "with a transition scene."
            )
        user_parts_trimmed.append(f"Player says: {player_input}")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(user_parts_trimmed)},
        ]

    # Reset chapter transition flag after building messages
    game.state.chapter_just_advanced = False

    return messages


def build_character_messages(
    game: LoadedGame,
    character: Character,
    memory: CharacterMemory | None,
    player_input: str,
    narrator_output: NarratorOutput,
    prior_responses: list[CharacterResponse],
    llm_config: LLMConfig,
) -> list[Message]:
    """Build the message list for a character agent."""
    # Memory block
    memory_block = ""
    if memory:
        facts = (
            "\n".join(f"- {f}" for f in memory.key_facts)
            if memory.key_facts
            else "(none)"
        )
        memory_block = f"Your memories:\n{memory.summary}\nKey facts:\n{facts}"

    # Relationship block
    relationships = ""
    if character.relationships:
        rels = "\n".join(f"- {k}: {v}" for k, v in character.relationships.items())
        relationships = f"Relationships:\n{rels}"

    system = CHARACTER_SYSTEM.format(
        name=character.name,
        role=character.role,
        personality=character.personality,
        secret=character.secret,
        relationships=relationships,
        memory_block=memory_block,
    )

    messages: list[Message] = [{"role": "system", "content": system}]

    # Include recent conversation (compact)
    recent = get_recent_conversation(game.conversation, max_turns=3)
    if recent:
        recent_text = format_conversation(recent)
        messages.append({"role": "user", "content": f"Recent:\n{recent_text}"})

    # This turn's context: narrator + player + prior characters
    turn_parts = [f"[Narrator]: {narrator_output.narration}"]
    turn_parts.append(f"[Player]: {player_input}")
    for pr in prior_responses:
        turn_parts.append(f"[{pr.character}]: {pr.response}")
    turn_context = "\n".join(turn_parts)

    messages.append(
        {
            "role": "user",
            "content": f"This turn:\n{turn_context}\n\nRespond as {character.name}.",
        }
    )

    # Token budget check
    budget = tokens_remaining(
        messages,
        llm_config.context_limit,
        CHARACTER_CONFIG.max_tokens or llm_config.default_max_tokens,
    )
    if budget < 0:
        # Drop recent conversation, keep only this turn
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"{turn_context}\n\nRespond as {character.name}.",
            },
        ]

    return messages


def build_memory_messages(
    character: Character,
    memory: CharacterMemory | None,
    turn_entries: list[ConversationEntry],
) -> list[Message]:
    """Build the message list for a memory update agent."""
    if memory:
        facts = (
            "\n".join(f"- {f}" for f in memory.key_facts)
            if memory.key_facts
            else "(none)"
        )
        current_memory = f"Summary: {memory.summary}\nFacts:\n{facts}"
    else:
        current_memory = "Summary: (new character, no memories yet)\nFacts:\n(none)"

    turn_text = format_conversation(turn_entries)

    system = MEMORY_UPDATE_SYSTEM.format(
        name=character.name,
    )

    messages: list[Message] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Current memory for {character.name}:\n{current_memory}\n\n"
                f"This turn:\n{turn_text}\n\n"
                f"Output memory updates for {character.name}."
            ),
        },
    ]

    return messages


def build_game_state_messages(
    game: LoadedGame,
    turn_entries: list[ConversationEntry],
) -> list[Message]:
    """Build the message list for the game state check agent."""
    current = game.chapters.get(game.state.current_chapter)
    if not current:
        return []

    beats_status: list[str] = []
    for beat in current.beats:
        hit = "x" if beat in game.state.beats_hit else " "
        beats_status.append(f"[{hit}] {beat}")
    beats_text = "\n".join(beats_status)

    turn_text = format_conversation(turn_entries)

    system = GAME_STATE_SYSTEM

    messages: list[Message] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Chapter: {current.title}\n"
                f"Beats:\n{beats_text}\n"
                f"Complete when: {current.completion}\n\n"
                f"This turn:\n{turn_text}\n\n"
                f"Check progress."
            ),
        },
    ]

    return messages


def build_summary_messages(
    game: LoadedGame,
    chapter: Chapter,
) -> list[Message]:
    """Build messages for generating a chapter summary.

    Fetches recent conversation directly from game.conversation.
    """
    recent = get_recent_conversation(game.conversation, max_turns=6)
    recent_text = format_conversation(recent)

    system = CHAPTER_SUMMARY_SYSTEM

    messages: list[Message] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Chapter: {chapter.title}\n"
                f"Chapter goal: {chapter.summary}\n"
                f"Key events:\n{recent_text}\n\n"
                f"Write a 2-3 sentence summary of what happened."
            ),
        },
    ]

    return messages


def build_rolling_summary_messages(
    existing_summary: str,
    old_entries: list[ConversationEntry],
) -> list[Message]:
    """Build messages for updating the rolling summary."""
    old_text = format_conversation(old_entries)

    system = ROLLING_SUMMARY_SYSTEM

    content_parts: list[str] = []
    if existing_summary:
        content_parts.append(f"Previous summary:\n{existing_summary}")
    content_parts.append(f"New events to incorporate:\n{old_text}")
    content_parts.append("Write an updated summary.")

    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(content_parts)},
    ]

    return messages
