# Phase 03: Turn Engine, Memory, and Summarization

> **Implementation note:** This is the most critical phase. The prompt templates in `agents/prompts.py` will need 5-10 iterations once they hit the real model. Keep all prompts in one file so changes are one-line edits. Don't over-abstract — keep agent functions simple and direct until prompts are proven via playtesting (Phase 05). Conversation entries are recorded as narrator → player → characters (narrative convention, not chronological order).

## 1. Overview

This phase implements the core gameplay loop -- the system that transforms a player's typed input into a living, breathing narrative turn. It is the bridge between the data layer (Phase 01) and the LLM layer (Phase 02), orchestrating every agent call, context window, memory update, and state transition that makes TheAct work.

After this phase is complete, we can:
- Accept player input and produce a full narrative turn (narrator + character responses)
- Assemble token-budgeted prompts for each agent type
- Stream narrator and character output in real time
- Update per-character memories in parallel after each turn
- Check chapter completion and advance the story
- Maintain a rolling summary of expired conversation turns
- Commit the entire turn atomically via git

What this phase does NOT cover: CLI/UI (Phase 04), game creation tooling (Phase 05), or the initial game content. The turn engine exposes an async API that the CLI will call.

### File Layout

```
src/theact/
  engine/
    __init__.py           # Public API re-exports
    turn.py               # TurnEngine -- the main orchestrator
    context.py            # Context assembly for each agent type
    types.py              # TurnResult, NarratorOutput, etc.
  agents/
    __init__.py           # Public API re-exports
    narrator.py           # Narrator agent
    character.py          # Character agent
    memory.py             # Memory update agent
    game_state.py         # Game state check agent
    summarizer.py         # Rolling summarization agent
    prompts.py            # All prompt templates in one place
```

---

## 2. Architecture

### 2.1 Module Relationships

```
                    CLI (Phase 04)
                        |
                        v
              +-------------------+
              |  engine/turn.py   |  <-- TurnEngine: the orchestrator
              |  run_turn()       |
              +-------------------+
                 |       |       |
      +----------+   +--+--+   +----------+
      |              |     |              |
      v              v     v              v
 engine/context.py   |     |    io/save_manager.py
 (build prompts)     |     |    versioning/git_save.py
                     |     |
            +--------+     +--------+
            |                       |
            v                       v
    agents/narrator.py      agents/character.py
    agents/memory.py        agents/game_state.py
    agents/summarizer.py
            |
            v
      llm/inference.py
      (complete, stream, complete_structured, stream_structured)
```

### 2.2 Data Flow Summary

```
LoadedGame + player_input
    |
    v
[context.py] --> system_prompt + messages for narrator
    |
    v
[narrator.py] --> NarratorOutput (narration, responding_characters, mood)
    |
    v
[context.py] --> system_prompt + messages for each character (sequential)
    |
    v
[character.py] --> plain text response per character
    |
    v
[memory.py + game_state.py] --> parallel post-turn processing
    |
    v
[save_manager + git_save] --> persist everything, git commit
    |
    v
TurnResult --> returned to caller (CLI)
```

### 2.3 Key Design Principles

1. **One task per LLM call.** Each agent does exactly one thing. No multi-step reasoning.
2. **Sequential characters, parallel post-turn.** Characters see prior responses. Memory and state checks are independent.
3. **Token budgets are hard limits.** Context assembly must fit within `LLMConfig.context_limit`. If it does not fit, older turns are trimmed and the rolling summary is updated.
4. **Prompts are tiny.** Every word in a system prompt must earn its place. A 7B model with 8K context cannot afford waste.
5. **Streaming for narrative, non-streaming for post-turn.** The player sees narrator and character tokens arrive in real time. Memory and state updates happen silently in the background.

---

## 3. Turn Engine

### 3.1 Types (`engine/types.py`)

```python
from dataclasses import dataclass, field
from theact.models.conversation import ConversationEntry


@dataclass
class NarratorOutput:
    """Parsed output from the narrator agent."""
    narration: str
    responding_characters: list[str]   # ordered list of character ids
    mood: str                          # e.g. "tense", "calm", "urgent"


@dataclass
class CharacterResponse:
    """A single character's response."""
    character: str      # character name
    content: str        # the dialogue/action text


@dataclass
class MemoryDiff:
    """Changes to apply to a character's memory."""
    character: str
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    update: list[dict[str, str]] = field(default_factory=list)  # [{old, new}]
    summary: str = ""


@dataclass
class GameStateResult:
    """Result of the game state check."""
    chapter_complete: bool
    reason: str
    new_beats: list[str] = field(default_factory=list)


@dataclass
class TurnResult:
    """Complete result of a single turn, returned to the caller."""
    turn: int
    narrator: NarratorOutput
    characters: list[CharacterResponse]
    memory_diffs: list[MemoryDiff]
    game_state: GameStateResult
    entries: list[ConversationEntry]      # all entries created this turn
    chapter_advanced: bool = False
    new_chapter: str | None = None
```

### 3.2 Turn Engine (`engine/turn.py`)

```python
import asyncio
from typing import AsyncIterator, Callable, Awaitable

from theact.models.game import LoadedGame
from theact.models.conversation import ConversationEntry
from theact.models.memory import CharacterMemory
from theact.models.chapter import ChapterSummary
from theact.llm.config import LLMConfig
from theact.engine.types import (
    TurnResult, NarratorOutput, CharacterResponse,
    MemoryDiff, GameStateResult,
)
from theact.engine.context import (
    build_narrator_messages,
    build_character_messages,
    build_memory_messages,
    build_game_state_messages,
    build_summary_messages,
)
from theact.agents.narrator import run_narrator
from theact.agents.character import run_character
from theact.agents.memory import run_memory_update
from theact.agents.game_state import run_game_state_check
from theact.agents.summarizer import run_summarization
from theact.io.save_manager import (
    save_state, append_conversation, save_memory, save_summaries,
)
from theact.versioning.git_save import commit_turn
from theact.llm.tokens import estimate_tokens

# Callback type for streaming output to the UI
StreamCallback = Callable[[str, str, str], Awaitable[None]]
# (source: "narrator"|"character", character_name: str, token: str)


async def run_turn(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
) -> TurnResult:
    """
    Execute a complete turn.

    Args:
        game: The fully loaded game state.
        player_input: The player's typed input.
        llm_config: LLM configuration.
        on_token: Optional callback for streaming tokens to the UI.
            Called as: await on_token(source, character_name, token_text)

    Returns:
        TurnResult with all turn data.

    Side effects:
        - Mutates game.state (turn++, beats_hit, chapter advance)
        - Mutates game.memories (applies memory diffs)
        - Appends to game.conversation
        - Writes all changes to disk
        - Creates a git commit
    """
    new_turn = game.state.turn + 1
    entries: list[ConversationEntry] = []

    # ── Step 1: Context Assembly + Narrator ──────────────────────────

    narrator_messages = build_narrator_messages(game, player_input, llm_config)
    narrator_output = await run_narrator(narrator_messages, llm_config, on_token)

    # Record narrator entry
    entries.append(ConversationEntry(
        turn=new_turn, role="narrator", content=narrator_output.narration
    ))
    # Record player entry
    entries.append(ConversationEntry(
        turn=new_turn, role="player", content=player_input
    ))

    # ── Step 2: Character Agents (sequential) ────────────────────────

    character_responses: list[CharacterResponse] = []
    prior_responses: list[CharacterResponse] = []

    for char_id in narrator_output.responding_characters:
        if char_id not in game.characters:
            continue  # skip unknown characters

        char = game.characters[char_id]
        char_memory = game.memories.get(char_id)

        char_messages = build_character_messages(
            game, char, char_memory, player_input,
            narrator_output, prior_responses, llm_config,
        )

        response = await run_character(
            char_messages, char.name, llm_config, on_token,
        )

        character_responses.append(response)
        prior_responses.append(response)

        entries.append(ConversationEntry(
            turn=new_turn, role="character",
            character=char.name, content=response.content,
        ))

    # ── Step 3: Post-turn Agents (parallel) ──────────────────────────

    # Build all post-turn tasks
    memory_tasks = []
    for char_id in narrator_output.responding_characters:
        if char_id not in game.characters:
            continue
        char = game.characters[char_id]
        char_memory = game.memories.get(char_id)
        mem_messages = build_memory_messages(
            char, char_memory, entries,
        )
        memory_tasks.append(run_memory_update(mem_messages, char_id, llm_config))

    state_messages = build_game_state_messages(game, entries)
    state_task = run_game_state_check(state_messages, llm_config)

    # Run all in parallel
    all_results = await asyncio.gather(
        *memory_tasks,
        state_task,
        return_exceptions=True,
    )

    # Unpack results
    import logging
    logger = logging.getLogger(__name__)

    memory_diffs: list[MemoryDiff] = []
    for result in all_results[:-1]:  # all except last (state check)
        if isinstance(result, Exception):
            logger.warning(
                f"Post-turn agent failed: {type(result).__name__}: {result}"
            )
            continue
        memory_diffs.append(result)

    state_result = all_results[-1]
    if isinstance(state_result, Exception):
        logger.warning(
            f"Post-turn agent failed: {type(state_result).__name__}: {state_result}"
        )
        state_result = GameStateResult(
            chapter_complete=False,
            reason="Game state check failed",
        )

    # ── Step 4: Apply Changes ────────────────────────────────────────

    # Update game state
    game.state.turn = new_turn
    for diff in memory_diffs:
        _apply_memory_diff(game, diff)
    for beat in state_result.new_beats:
        if beat not in game.state.beats_hit:
            game.state.beats_hit.append(beat)

    # Append all conversation entries
    for entry in entries:
        game.conversation.append(entry)
        append_conversation(game.save_path, entry)

    # ── Step 5: Chapter Advancement ──────────────────────────────────

    chapter_advanced = False
    new_chapter = None

    # Skip chapter advancement if the game is already complete
    if state_result.chapter_complete and not game.state.game_complete:
        chapter_advanced, new_chapter = await _advance_chapter(
            game, llm_config,
        )

    # ── Step 6: Rolling Summary (if needed) ──────────────────────────

    await _maybe_update_rolling_summary(game, llm_config)

    # ── Step 7: Persist + Git Commit ────────────────────────────────

    # Single save point: write all state, memories, and summaries to disk
    # just before the git commit. This avoids multiple save_state calls
    # scattered across helper functions and keeps the write atomic.
    save_state(game.save_path, game.state)
    for char_id, mem in game.memories.items():
        save_memory(game.save_path, mem)

    commit_summary = narrator_output.narration[:60].replace("\n", " ")
    commit_turn(game.save_path, new_turn, commit_summary)

    return TurnResult(
        turn=new_turn,
        narrator=narrator_output,
        characters=character_responses,
        memory_diffs=memory_diffs,
        game_state=state_result,
        entries=entries,
        chapter_advanced=chapter_advanced,
        new_chapter=new_chapter,
    )


def _fuzzy_match(target: str, candidates: list[str]) -> int | None:
    """Find the best fuzzy match for target in candidates.

    Uses case-insensitive, whitespace-normalized comparison.
    Returns the index of the matching candidate, or None if no match.

    NOTE: Exact string matching is unreliable with 7B models — the model
    rarely reproduces existing fact text verbatim. In practice, the
    `summary` replacement is the reliable memory evolution mechanism,
    and `add` is reliable, but `remove`/`update` may miss.
    """
    def normalize(s: str) -> str:
        return " ".join(s.lower().split())

    norm_target = normalize(target)
    for i, candidate in enumerate(candidates):
        if normalize(candidate) == norm_target:
            return i
    return None


def _apply_memory_diff(game: LoadedGame, diff: MemoryDiff) -> None:
    """Apply a MemoryDiff to the in-memory game state."""
    char_id = diff.character

    if char_id not in game.memories:
        game.memories[char_id] = CharacterMemory(
            character=game.characters[char_id].name,
            summary="",
            key_facts=[],
        )

    mem = game.memories[char_id]

    # Remove facts (fuzzy match -- 7B models rarely reproduce text exactly)
    for fact in diff.remove:
        idx = _fuzzy_match(fact, mem.key_facts)
        if idx is not None:
            mem.key_facts.pop(idx)

    # Update facts (fuzzy match)
    for upd in diff.update:
        old = upd.get("old", "")
        new = upd.get("new", "")
        idx = _fuzzy_match(old, mem.key_facts)
        if idx is not None:
            mem.key_facts[idx] = new

    # Add facts
    for fact in diff.add:
        if fact not in mem.key_facts:
            mem.key_facts.append(fact)

    # Enforce max ~10 key_facts (prune oldest)
    if len(mem.key_facts) > 10:
        mem.key_facts = mem.key_facts[-10:]

    # Update summary
    if diff.summary:
        mem.summary = diff.summary


async def _advance_chapter(
    game: LoadedGame,
    llm_config: LLMConfig,
) -> tuple[bool, str | None]:
    """Handle chapter completion: generate summary, advance state."""
    current = game.chapters.get(game.state.current_chapter)
    if not current or not current.next:
        # Final chapter — mark the game as complete
        if current:
            game.state.game_complete = True
        return False, None

    # Generate chapter summary via summarizer
    summary_messages = build_summary_messages(game, current)
    chapter_summary_text = await run_summarization(summary_messages, llm_config)

    # Create and save chapter summary
    summary = ChapterSummary(
        chapter_id=current.id,
        title=current.title,
        summary=chapter_summary_text,
    )
    game.chapter_summaries.append(summary)
    save_summaries(game.save_path, game.chapter_summaries)

    # Advance to next chapter
    game.state.current_chapter = current.next
    game.state.beats_hit = []
    game.state.chapter_history.append(current.id)
    game.state.chapter_just_advanced = True
    # NOTE: save_state is NOT called here — all saves are consolidated
    # in run_turn just before the git commit (single write, atomic).

    return True, current.next


async def _maybe_update_rolling_summary(
    game: LoadedGame,
    llm_config: LLMConfig,
) -> None:
    """Trigger rolling summarization if conversation exceeds token budget.

    NOTE: We only count entries added since the last summarization
    (game.state.last_summarized_turn). Without this, the token count for
    the full conversation always exceeds the threshold after the first
    summary, causing a summarization LLM call on every single turn.
    """
    SUMMARY_THRESHOLD = 1500  # tokens of conversation history before trimming
    KEEP_RECENT = 4           # number of recent turns to keep verbatim

    # Only count entries added since the last summarization
    new_entries = [
        e for e in game.conversation
        if e.turn > game.state.last_summarized_turn
    ]
    conv_text = "\n".join(e.content for e in new_entries)
    conv_tokens = estimate_tokens(conv_text)

    if conv_tokens <= SUMMARY_THRESHOLD:
        return

    # Find the cutoff: keep the last KEEP_RECENT turns
    turns_seen = set()
    cutoff_idx = len(game.conversation)
    for i in range(len(game.conversation) - 1, -1, -1):
        turns_seen.add(game.conversation[i].turn)
        if len(turns_seen) > KEEP_RECENT:
            cutoff_idx = i + 1
            break

    if cutoff_idx <= 0:
        return

    # The entries to summarize (will be trimmed from verbatim history)
    old_entries = game.conversation[:cutoff_idx]

    from theact.engine.context import build_rolling_summary_messages
    summary_messages = build_rolling_summary_messages(
        game.state.rolling_summary, old_entries,
    )
    new_summary = await run_summarization(summary_messages, llm_config)

    game.state.rolling_summary = new_summary

    # Record which turn we summarized up to, so we don't re-count
    # already-summarized entries on the next turn.
    cutoff_turn = max(e.turn for e in old_entries)
    game.state.last_summarized_turn = cutoff_turn
    # NOTE: save_state is NOT called here — all saves are consolidated
    # in run_turn just before the git commit (single write, atomic).
```

---

## 4. Context Assembly

Context assembly is the most critical code in the system. It decides what each agent sees. Every token wasted here is a token the 7B model cannot use for reasoning or output.

### 4.1 Token Budget Strategy

Each agent call has a token budget calculated as:

```
available = context_limit - max_completion_tokens - system_prompt_tokens
```

Context is filled in priority order:
1. **System prompt** (always included, fixed cost)
2. **Current turn data** (player input, narrator output, prior character responses)
3. **Character memory / chapter info** (injected into system prompt)
4. **Recent conversation** (last 3-5 verbatim turns)
5. **Rolling summary** (compressed older history)

If the budget is tight, we reduce recent conversation turns first (from 5 down to 3), then truncate the rolling summary.

### 4.2 Context Assembly Functions (`engine/context.py`)

```python
from pathlib import Path

from theact.models.game import LoadedGame
from theact.models.character import Character
from theact.models.memory import CharacterMemory
from theact.models.conversation import ConversationEntry
from theact.models.chapter import Chapter
from theact.engine.types import NarratorOutput, CharacterResponse
from theact.llm.config import LLMConfig, NARRATOR_CONFIG, CHARACTER_CONFIG
from theact.llm.tokens import estimate_tokens, estimate_messages_tokens, tokens_remaining
from theact.agents.prompts import (
    NARRATOR_SYSTEM, CHARACTER_SYSTEM,
    MEMORY_UPDATE_SYSTEM, GAME_STATE_SYSTEM,
    CHAPTER_SUMMARY_SYSTEM, ROLLING_SUMMARY_SYSTEM,
)

Message = dict[str, str]


def _get_recent_conversation(
    conversation: list[ConversationEntry],
    max_turns: int = 4,
) -> list[ConversationEntry]:
    """Get the last N turns of conversation (all entries within those turns)."""
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


def _format_conversation(entries: list[ConversationEntry]) -> str:
    """Format conversation entries into a compact text block."""
    lines = []
    for e in entries:
        if e.role == "narrator":
            lines.append(f"[Narrator]: {e.content}")
        elif e.role == "player":
            lines.append(f"[Player]: {e.content}")
        elif e.role == "character":
            lines.append(f"[{e.character}]: {e.content}")
    return "\n".join(lines)


def _format_chapter_context(game: LoadedGame) -> str:
    """Format chapter information: completed summaries + current chapter + upcoming titles."""
    parts = []

    # Completed chapters (2-3 line summaries)
    if game.chapter_summaries:
        parts.append("COMPLETED CHAPTERS:")
        for cs in game.chapter_summaries:
            parts.append(f"- {cs.title}: {cs.summary}")

    # Current chapter (full definition)
    current = game.chapters.get(game.state.current_chapter)
    if current:
        beats_status = []
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
    current_idx = chapter_order.index(game.state.current_chapter) if game.state.current_chapter in chapter_order else -1
    upcoming = chapter_order[current_idx + 1:] if current_idx >= 0 else []
    if upcoming:
        titles = [game.chapters[cid].title for cid in upcoming if cid in game.chapters]
        if titles:
            parts.append(f"\nUPCOMING: {', '.join(titles)}")

    return "\n".join(parts)


def build_narrator_messages(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
) -> list[Message]:
    """Build the message list for the narrator agent."""
    chapter_context = _format_chapter_context(game)
    recent = _get_recent_conversation(game.conversation)
    recent_text = _format_conversation(recent)

    # Active characters for this chapter
    current_chapter = game.chapters.get(game.state.current_chapter)
    active_chars = current_chapter.characters if current_chapter else list(game.characters.keys())
    char_names = ", ".join(
        game.characters[cid].name for cid in active_chars if cid in game.characters
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
    # SINGLE user message. Some APIs merge or behave unpredictably with
    # multiple consecutive same-role messages, so we consolidate here.
    user_parts: list[str] = []

    if game.state.rolling_summary:
        user_parts.append(f"Story so far: {game.state.rolling_summary}")

    if recent_text:
        user_parts.append(f"Recent conversation:\n{recent_text}")

    # Opening scene guidance (Issue 1.4)
    if not game.conversation and game.state.turn == 0:
        user_parts.append(
            "This is the opening scene. Set the stage and introduce the setting."
        )

    # Chapter transition signal (Issue 6.2)
    if game.state.chapter_just_advanced:
        user_parts.append(
            "The previous chapter is complete. Begin the new chapter "
            "with a transition scene."
        )

    user_parts.append(f"Player says: {player_input}")

    messages.append({
        "role": "user",
        "content": "\n\n".join(user_parts),
    })

    # Token budget check -- trim recent conversation if needed
    budget = tokens_remaining(
        messages, llm_config.context_limit,
        NARRATOR_CONFIG.max_tokens or llm_config.default_max_tokens,
    )
    if budget < 0:
        # Retry with fewer turns
        recent = _get_recent_conversation(game.conversation, max_turns=2)
        recent_text = _format_conversation(recent)
        user_parts_trimmed: list[str] = []
        if game.state.rolling_summary:
            user_parts_trimmed.append(
                f"Story so far: {game.state.rolling_summary}"
            )
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
        facts = "\n".join(f"- {f}" for f in memory.key_facts) if memory.key_facts else "(none)"
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
    recent = _get_recent_conversation(game.conversation, max_turns=3)
    if recent:
        recent_text = _format_conversation(recent)
        messages.append({"role": "user", "content": f"Recent:\n{recent_text}"})

    # This turn's context: narrator + player + prior characters
    turn_parts = [f"[Narrator]: {narrator_output.narration}"]
    turn_parts.append(f"[Player]: {player_input}")
    for pr in prior_responses:
        turn_parts.append(f"[{pr.character}]: {pr.content}")
    turn_context = "\n".join(turn_parts)

    messages.append({
        "role": "user",
        "content": f"This turn:\n{turn_context}\n\nRespond as {character.name}.",
    })

    # Token budget check
    budget = tokens_remaining(
        messages, llm_config.context_limit,
        CHARACTER_CONFIG.max_tokens or llm_config.default_max_tokens,
    )
    if budget < 0:
        # Drop recent conversation, keep only this turn
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{turn_context}\n\nRespond as {character.name}."},
        ]

    return messages


def build_memory_messages(
    character: Character,
    memory: CharacterMemory | None,
    turn_entries: list[ConversationEntry],
) -> list[Message]:
    """Build the message list for a memory update agent."""
    current_memory = ""
    if memory:
        facts = "\n".join(f"- {f}" for f in memory.key_facts) if memory.key_facts else "(none)"
        current_memory = f"Summary: {memory.summary}\nFacts:\n{facts}"
    else:
        current_memory = "Summary: (new character, no memories yet)\nFacts:\n(none)"

    turn_text = _format_conversation(turn_entries)

    system = MEMORY_UPDATE_SYSTEM.format(
        name=character.name,
    )

    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Current memory for {character.name}:\n{current_memory}\n\n"
            f"This turn:\n{turn_text}\n\n"
            f"Output memory updates for {character.name}."
        )},
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

    beats_status = []
    for beat in current.beats:
        hit = "x" if beat in game.state.beats_hit else " "
        beats_status.append(f"[{hit}] {beat}")
    beats_text = "\n".join(beats_status)

    turn_text = _format_conversation(turn_entries)

    system = GAME_STATE_SYSTEM

    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Chapter: {current.title}\n"
            f"Beats:\n{beats_text}\n"
            f"Complete when: {current.completion}\n\n"
            f"This turn:\n{turn_text}\n\n"
            f"Check progress."
        )},
    ]

    return messages


def build_summary_messages(
    game: LoadedGame,
    chapter: Chapter,
) -> list[Message]:
    """Build messages for generating a chapter summary.

    NOTE: Recent conversation is fetched directly from game.conversation
    rather than passed in, since the turn_entries parameter was unused.
    """
    recent = _get_recent_conversation(game.conversation, max_turns=6)
    recent_text = _format_conversation(recent)

    system = CHAPTER_SUMMARY_SYSTEM

    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Chapter: {chapter.title}\n"
            f"Chapter goal: {chapter.summary}\n"
            f"Key events:\n{recent_text}\n\n"
            f"Write a 2-3 sentence summary of what happened."
        )},
    ]

    return messages


def build_rolling_summary_messages(
    existing_summary: str,
    old_entries: list[ConversationEntry],
) -> list[Message]:
    """Build messages for updating the rolling summary."""
    old_text = _format_conversation(old_entries)

    system = ROLLING_SUMMARY_SYSTEM

    content_parts = []
    if existing_summary:
        content_parts.append(f"Previous summary:\n{existing_summary}")
    content_parts.append(f"New events to incorporate:\n{old_text}")
    content_parts.append("Write an updated summary.")

    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(content_parts)},
    ]

    return messages
```

---

## 5. Agent Implementations

### 5.1 Prompt Templates (`agents/prompts.py`)

This is the most important file in the project. These prompts determine whether a 7B model can do its job. Every word is chosen carefully. Prompts are short, direct, single-task, and include output format examples.

```python
# src/theact/agents/prompts.py
"""
All prompt templates for TheAct agents.

Design principles for 7B-class models:
- One task per prompt. Never ask for two things.
- Show the exact output format. Use a concrete example.
- Keep system prompts under ~300 tokens.
- Use imperative mood. No hedging.
- State constraints as rules, not suggestions.
"""

# ─── NARRATOR ────────────────────────────────────────────────────────────

NARRATOR_SYSTEM = """\
You are the narrator of a text RPG.

SETTING: {world_setting}
TONE: {world_tone}
RULES: {world_rules}

{chapter_context}

ACTIVE CHARACTERS: {active_characters}

YOUR TASK:
1. Write narration responding to the player's action. 150-300 words. Second person present tense.
2. Decide which characters respond and in what order.
3. Guide the story toward unfinished beats. Do NOT skip beats.

Output a YAML block:

```yaml
narration: |
  You step into the clearing. The air smells wrong — metallic,
  like a storm that never came. Something crunches under your boot.
responding_characters:
  - maya
  - joaquin
mood: tense
```

OUTPUT RULES:
- Only list characters from ACTIVE CHARACTERS.
- responding_characters can be empty if no one speaks.
- mood is one of: tense, calm, urgent, mysterious, humorous, dramatic, melancholic.
- Never speak for the player. Never decide what the player does next."""

# ─── CHARACTER ───────────────────────────────────────────────────────────

CHARACTER_SYSTEM = """\
You are {name} in a text RPG. Stay in character.

ROLE: {role}
PERSONALITY: {personality}
SECRET: {secret}
{relationships}

{memory_block}

Write {name}'s response to what just happened. Dialogue and actions only.
50-150 words. Stay in character. Do not narrate for others.
Do not use quotation marks around actions — write actions as plain text.

Example format (for illustration only):
She sets down the wrench and wipes her hands on her jeans. "Three days. That's how long the water will last if we're careful." She glances toward the tree line. "Less if we're not.\""""

# ─── MEMORY UPDATE ───────────────────────────────────────────────────────

MEMORY_UPDATE_SYSTEM = """\
You manage {name}'s memory in a text RPG.

Read what happened this turn. Update {name}'s memory.
Only include things {name} witnessed or learned.
Do NOT include things {name} would not know.

Output a YAML block:

```yaml
add:
  - "New fact {name} learned or experienced"
remove:
  - "Exact text of a fact that is outdated or wrong"
update:
  - old: "Exact text of existing fact"
    new: "Corrected or updated version"
summary: |
  Updated 3-5 sentence summary of what {name} knows, feels, and has experienced.
  Merge new information into the existing summary. Do not repeat old details
  unless still relevant.
```

RULES:
- add/remove/update lists can be empty.
- Key facts are short, specific statements. Max 10 total.
- The summary replaces the old summary entirely.
- If nothing meaningful changed, output empty lists and keep the summary."""

# ─── GAME STATE CHECK ───────────────────────────────────────────────────

GAME_STATE_SYSTEM = """\
You check story progress in a text RPG.

Look at the chapter's beats and completion condition.
Compare against what happened this turn.

Output a YAML block:

```yaml
chapter_complete: false
reason: "One sentence explaining progress or why not complete"
new_beats:
  - "Exact beat text that was hit this turn"
```

RULES:
- Only mark beats that clearly happened this turn.
- chapter_complete is true ONLY when the completion condition is fully met.
- new_beats contains the exact text of beats from the chapter definition.
- If no beats were hit, new_beats is an empty list."""

# ─── CHAPTER SUMMARY ────────────────────────────────────────────────────

CHAPTER_SUMMARY_SYSTEM = """\
Summarize what happened in this chapter of a text RPG.
Write 2-3 sentences. Include key events, character actions, and discoveries.
Be specific. Use past tense."""

# ─── ROLLING SUMMARY ────────────────────────────────────────────────────

ROLLING_SUMMARY_SYSTEM = """\
You maintain a running summary of a text RPG's story.

Merge the new events into the previous summary.
Keep it under 5 sentences. Drop minor details. Keep key plot points,
character relationships, and discoveries.
Write in past tense. Be specific."""
```

### 5.2 Narrator Agent (`agents/narrator.py`)

```python
from typing import Callable, Awaitable

from theact.llm.config import LLMConfig, NARRATOR_CONFIG
from theact.llm.inference import stream_structured
from theact.llm.streaming import StreamChunk
from theact.engine.types import NarratorOutput

Message = dict[str, str]
StreamCallback = Callable[[str, str, str], Awaitable[None]]


async def run_narrator(
    messages: list[Message],
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
) -> NarratorOutput:
    """
    Run the narrator agent. Streams tokens for live display,
    then parses the structured YAML output.

    Returns NarratorOutput with narration, responding_characters, and mood.
    """
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

    # Stream tokens to UI
    async for chunk in stream_iter:
        if on_token and chunk.content:
            await on_token("narrator", "", chunk.content)

    # Get parsed result
    result = await result_future
    data = result.data

    return NarratorOutput(
        narration=data.get("narration", "").strip(),
        responding_characters=data.get("responding_characters", []),
        mood=data.get("mood", "calm"),
    )
```

### 5.3 Character Agent (`agents/character.py`)

```python
from typing import Callable, Awaitable

from theact.llm.config import LLMConfig, CHARACTER_CONFIG
from theact.llm.inference import stream
from theact.llm.streaming import collect_stream
from theact.engine.types import CharacterResponse

Message = dict[str, str]
StreamCallback = Callable[[str, str, str], Awaitable[None]]


async def run_character(
    messages: list[Message],
    character_name: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
) -> CharacterResponse:
    """
    Run a character agent. Streams tokens for live display.
    Returns plain text character response.
    """
    content_parts: list[str] = []

    async for chunk in await stream(
        messages=messages,
        llm_config=llm_config,
        agent_config=CHARACTER_CONFIG,
    ):
        if chunk.content:
            content_parts.append(chunk.content)
            if on_token:
                await on_token("character", character_name, chunk.content)

    content = "".join(content_parts)

    return CharacterResponse(
        character=character_name,
        content=content.strip(),
    )
```

### 5.4 Memory Update Agent (`agents/memory.py`)

```python
from theact.llm.config import LLMConfig, MEMORY_UPDATE_CONFIG
from theact.llm.inference import complete_structured
from theact.engine.types import MemoryDiff

Message = dict[str, str]


async def run_memory_update(
    messages: list[Message],
    character_id: str,
    llm_config: LLMConfig,
) -> MemoryDiff:
    """
    Run the memory update agent for a single character.
    Non-streaming (runs in background).
    Returns a MemoryDiff with add/remove/update operations.
    """
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

    return MemoryDiff(
        character=character_id,
        add=data.get("add", []) or [],
        remove=data.get("remove", []) or [],
        update=data.get("update", []) or [],
        summary=data.get("summary", ""),
    )
```

### 5.5 Game State Agent (`agents/game_state.py`)

```python
from theact.llm.config import LLMConfig, GAME_STATE_CONFIG
from theact.llm.inference import complete_structured
from theact.engine.types import GameStateResult

Message = dict[str, str]


async def run_game_state_check(
    messages: list[Message],
    llm_config: LLMConfig,
) -> GameStateResult:
    """
    Run the game state check agent.
    Non-streaming (runs in background).
    Returns chapter completion status and any new beats hit.
    """
    result = await complete_structured(
        messages=messages,
        llm_config=llm_config,
        agent_config=GAME_STATE_CONFIG,
        yaml_hint=(
            "chapter_complete: false\\n"
            "reason: ...\\n"
            "new_beats:\\n  - ..."
        ),
    )

    data = result.data

    return GameStateResult(
        chapter_complete=bool(data.get("chapter_complete", False)),
        reason=data.get("reason", ""),
        new_beats=data.get("new_beats", []) or [],
    )
```

### 5.6 Summarizer Agent (`agents/summarizer.py`)

```python
from theact.llm.config import LLMConfig, AgentLLMConfig
from theact.llm.inference import complete

Message = dict[str, str]

SUMMARIZER_CONFIG = AgentLLMConfig(
    temperature=0.3,
    max_tokens=300,
    structured=False,
)


async def run_summarization(
    messages: list[Message],
    llm_config: LLMConfig,
) -> str:
    """
    Run the summarization agent (used for both chapter summaries and rolling summaries).
    Returns plain text summary.
    """
    result = await complete(
        messages=messages,
        llm_config=llm_config,
        agent_config=SUMMARIZER_CONFIG,
    )

    return result.content.strip()
```

---

## 6. Rolling Summarization

### 6.1 When It Triggers

Rolling summarization is checked at the end of every turn (Step 6 in the turn engine). It triggers when the total estimated token count of the conversation history exceeds `SUMMARY_THRESHOLD` (1500 tokens, approximately 6000 characters or 15-20 turns of dialogue).

### 6.2 How It Works

1. Count estimated tokens for the full conversation.
2. If over threshold, identify the cutoff: keep the last `KEEP_RECENT` turns (4 turns) verbatim.
3. Take all entries before the cutoff.
4. Send them to the summarizer along with the existing `rolling_summary`.
5. The summarizer merges the old summary with the new events into an updated summary of at most 5 sentences.
6. The updated summary is written to `state.yaml`'s `rolling_summary` field.

### 6.3 Incremental Merge, Not Re-summarization

The rolling summary is an incremental merge. Each time it fires, it takes:
- The previous rolling summary (already compressed older history)
- The oldest N entries being trimmed from the verbatim window

And produces a new summary that incorporates both. This means the summary grows in information density but not in length. Old minor details naturally get dropped as newer, more important events take their place.

### 6.4 Prompt Template

The `ROLLING_SUMMARY_SYSTEM` prompt (shown in Section 5.1) instructs the model to:
- Merge new events into the previous summary
- Keep it under 5 sentences
- Drop minor details
- Keep key plot points, character relationships, and discoveries
- Use past tense

### 6.5 Example

Before summarization:
```
rolling_summary: "Player woke on the beach after the crash. Found Maya beyond the headland."
```

Old entries being trimmed:
```
[Narrator]: The jungle closes in around you...
[Player]: I ask Maya about the sounds we heard last night.
[Maya]: She hesitates. "Drums. But that's impossible — we checked. No one else is on this island."
```

After summarization:
```
rolling_summary: "Player woke on the beach after the crash and found Maya beyond the headland. They explored the jungle together. Maya confirmed hearing drums at night but insists no one else is on the island."
```

---

## 7. Chapter Advancement

### 7.1 When It Happens

Chapter advancement occurs within the turn engine when the game state agent returns `chapter_complete: true`.

### 7.2 Sequence

1. **Generate chapter summary.** The summarizer agent produces a 2-3 sentence summary of the completed chapter using the `CHAPTER_SUMMARY_SYSTEM` prompt and the last several turns of conversation.

2. **Save chapter summary.** A `ChapterSummary` is created and appended to `game.chapter_summaries`. The full list is written to `summaries.yaml`.

3. **Advance state.** The following fields on `GameState` are updated:
   - `current_chapter` = the `next` field of the completed chapter
   - `beats_hit` = `[]` (reset for the new chapter)
   - `chapter_history` appends the completed chapter's id

> **GameState additions from this phase:** `rolling_summary: str = ""`, `last_summarized_turn: int = 0`, `game_complete: bool = False`, `chapter_just_advanced: bool = False`

4. **Save state.** Updated `state.yaml` is written to disk.

5. **Return to caller.** The `TurnResult` includes `chapter_advanced=True` and `new_chapter` with the new chapter's id, so the CLI can display a chapter transition message.

### 7.3 Final Chapter Handling

If the completed chapter has `next: null`, no advancement occurs. The `_advance_chapter` function sets `game.state.game_complete = True` and returns `(False, None)`. Once `game_complete` is True, `run_turn` skips the game state check to avoid redundant completion detection. Phase 04 (CLI) will handle displaying an end-of-game message based on `game.state.game_complete`.

---

## 8. Token Budget Management

### 8.1 Budget Breakdown

For an 8192-token context window with a 600-token max completion (narrator):

```
Context limit:                    8192 tokens
Max completion tokens:            -600 tokens
Available for prompt:             7592 tokens
  System prompt (narrator):       ~500 tokens
  Chapter context:                ~300 tokens (varies)
  Rolling summary:                ~150 tokens
  Recent conversation (4 turns):  ~500-1500 tokens
  Player input:                   ~50 tokens
  Message overhead:               ~30 tokens
  ─────────────────────────────────
  Remaining buffer:               ~5000-4000 tokens
```

This budget is generous for a narrator call. Character calls are even lighter because they have smaller system prompts and fewer context elements. Memory and game state calls are the lightest.

### 8.2 Budget Per Agent Type

| Agent | System Prompt | Context Injected | Max Completion | Budget Concern |
|---|---|---|---|---|
| Narrator | ~500 tok | Chapter + summary + recent conv + player input | 600 tok | Moderate |
| Character | ~300 tok | Memory + recent conv + this turn | 400 tok | Moderate |
| Memory Update | ~200 tok | Current memory + this turn's entries | 500 tok | Low |
| Game State | ~150 tok | Chapter beats + this turn's entries | 200 tok | Very low |
| Summarizer | ~50 tok | Old summary + entries to merge | 300 tok | Low |

### 8.3 Overflow Handling

Each `build_*_messages()` function in `context.py` checks the remaining token budget after assembly. If the budget is negative:

1. **Narrator/Character**: Reduce `max_turns` for recent conversation from 4 to 2. If still over, drop recent conversation entirely and rely on rolling summary.
2. **Memory/State**: These prompts are small enough that overflow should never occur. If it does, truncate the turn entries to the most recent 500 tokens.
3. **Summarizer**: Truncate old entries to fit. This loses some detail but is acceptable since the point is compression anyway.

---

## 9. Implementation Steps

Build in this order. Each step should produce working code before moving to the next.

### Step 1: Engine types

Create `src/theact/engine/__init__.py` and `src/theact/engine/types.py`. Define `NarratorOutput`, `CharacterResponse`, `MemoryDiff`, `GameStateResult`, and `TurnResult` as shown in Section 3.1.

### Step 2: Prompt templates

Create `src/theact/agents/__init__.py` and `src/theact/agents/prompts.py` with all prompt templates from Section 5.1. These are string constants with `{placeholders}`.

### Step 3: Individual agents

Implement one agent at a time. Each agent is a single async function in its own file:

1. `agents/summarizer.py` -- simplest agent, no structured output. Implement and test with a manual script that calls it with sample data against the live API.

2. `agents/memory.py` -- structured output. Test with a sample character memory and fake turn entries.

3. `agents/game_state.py` -- structured output. Test with sample chapter beats and fake turn entries.

4. `agents/character.py` -- streaming, plain text. Test with sample character definition and narrator output.

5. `agents/narrator.py` -- streaming + structured output. Test with sample world/chapter data and player input.

### Step 4: Context assembly

Implement `engine/context.py` with all `build_*_messages()` functions. Test by:
- Creating a sample `LoadedGame` with the lost-island game data
- Calling each builder and printing the resulting messages
- Verifying token estimates are within budget
- Verifying that conversation trimming works when history is long

### Step 5: Turn engine

Implement `engine/turn.py` with `run_turn()` and all helper functions. This wires everything together.

### Step 6: Integration testing

Write `scripts/test_turn.py` that:
1. Creates a save from the lost-island game
2. Runs 3 turns with scripted player inputs
3. Verifies conversation.yaml, state.yaml, and memory files are updated
4. Verifies git commits exist
5. Prints all output for manual review

### Step 7: Edge cases

- Test chapter advancement by manually setting beats_hit to almost-complete
- Test rolling summarization by running enough turns to exceed the threshold
- Test with unknown character ids in responding_characters
- Test with empty responding_characters (narrator-only turn)
- Test token budget overflow with very long player input

---

## 10. Verification

### 10.1 Unit Tests (No API required)

```
tests/
  test_context.py          # Context assembly tests
  test_engine_types.py     # Type construction tests
  test_prompts.py          # Prompt template formatting tests
```

**test_context.py:**
- `test_get_recent_conversation` -- returns correct number of turns, handles empty
- `test_format_conversation` -- formats each role correctly
- `test_format_chapter_context` -- includes completed, current (with beat status), upcoming
- `test_build_narrator_messages` -- produces valid message list within token budget
- `test_build_character_messages` -- includes memory, relationships, prior responses
- `test_build_memory_messages` -- includes current memory and turn entries
- `test_build_game_state_messages` -- includes beats with status
- `test_token_budget_overflow` -- verifies trimming when conversation is too long

**test_prompts.py:**
- `test_narrator_system_format` -- all placeholders filled, no orphan braces
- `test_character_system_format` -- handles empty memory, empty relationships
- `test_memory_system_format` -- character name injected correctly

### 10.2 Integration Test Script (`scripts/test_turn.py`)

```python
"""
Integration test for the turn engine.
Run: uv run python scripts/test_turn.py

Requires VENICE_API_KEY in environment or .env file.
Runs 3 turns against the live API with the lost-island game.
"""
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from theact.llm.config import load_llm_config
from theact.io.save_manager import create_save, load_save
from theact.engine.turn import run_turn


async def on_token(source: str, character: str, token: str):
    """Print tokens as they arrive."""
    label = character if character else source
    print(token, end="", flush=True)


async def main():
    llm_config = load_llm_config()
    save_id = "test-turn-001"

    # Create a fresh save
    print("Creating save...")
    save_path = create_save("lost-island", save_id, "Alex")
    print(f"Save created at {save_path}\n")

    # Load the game
    game = load_save(save_id)

    # Scripted player inputs
    inputs = [
        "I open my eyes and try to stand up.",
        "I look around for anything useful in the wreckage.",
        "I walk along the beach looking for other survivors.",
    ]

    for i, player_input in enumerate(inputs):
        print(f"\n{'='*60}")
        print(f"TURN {i+1}: Player says: {player_input}")
        print(f"{'='*60}\n")

        result = await run_turn(game, player_input, llm_config, on_token)

        print(f"\n\n--- Turn {result.turn} Summary ---")
        print(f"Mood: {result.narrator.mood}")
        print(f"Characters responded: {[c.character for c in result.characters]}")
        print(f"Beats hit: {game.state.beats_hit}")
        print(f"Memory diffs: {len(result.memory_diffs)}")
        if result.chapter_advanced:
            print(f"CHAPTER ADVANCED to: {result.new_chapter}")
        print()

        # Reload game state for next turn
        game = load_save(save_id)

    print("\n=== FINAL STATE ===")
    print(f"Turn: {game.state.turn}")
    print(f"Chapter: {game.state.current_chapter}")
    print(f"Beats hit: {game.state.beats_hit}")
    print(f"Rolling summary: {game.state.rolling_summary}")
    print(f"Memories: {list(game.memories.keys())}")
    for char_id, mem in game.memories.items():
        print(f"  {char_id}: {mem.summary[:100]}...")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
```

### 10.3 Manual Verification Checklist

Phase 03 is complete when all of the following pass:

1. **Unit tests pass:** `uv run pytest tests/test_context.py tests/test_engine_types.py tests/test_prompts.py`

2. **Integration script runs 3 turns:** `uv run python scripts/test_turn.py` completes without errors.

3. **Narrator output is structured:** Each turn produces valid `NarratorOutput` with narration text, a character list, and a mood.

4. **Characters respond in order:** If narrator says `[maya, joaquin]`, Maya responds first, then Joaquin sees Maya's response and responds second.

5. **Streaming works:** Tokens appear incrementally during narrator and character responses (not all at once).

6. **Memory files exist:** After 3 turns, `memory/maya.yaml` exists and contains a summary and key facts.

7. **Game state tracks beats:** `state.yaml` shows `beats_hit` accumulating over turns.

8. **Git history is correct:** `git log --oneline` in the save directory shows 4 commits (1 initial + 3 turns).

9. **Undo works end-to-end:** After 3 turns, undo 1 turn, then load the save -- turn count is 2, conversation has 2 turns of content.

10. **Token budgets hold:** No agent call exceeds the context limit. Verify by adding logging to `build_*_messages()` that prints estimated token usage.

11. **Prompt sizes are small:** Each system prompt template, when formatted with real data, is under 500 tokens (verified via `estimate_tokens()`).

### 10.4 Live Testing & Regression Capture

This is the most important live testing phase. The prompts will meet reality here, and reality always wins. The goal is to iterate on prompts based on real model output and capture every fix as a regression test.

**Step 1 — Run `scripts/test_turn.py` and analyze every response:**
- Does the narrator output valid YAML? If not, note which field fails and why. Adjust the prompt template or YAML hint.
- Does the narrator pick appropriate characters? If it always picks all characters, the prompt may need "only pick characters who would naturally respond."
- Are character responses in-character? If Maya sounds like Joaquin, the personality prompts need sharper differentiation.
- Are character responses aware of prior responses? If Maya says something and Joaquin ignores it, check that `build_character_messages` actually includes prior responses.
- Does the memory update agent produce valid diffs? If it hallucinates facts, the prompt needs "only include things [name] directly witnessed."
- Does the game state agent correctly identify beats? If it marks beats that didn't happen, the prompt needs "only mark beats that explicitly occurred this turn."
- Is the rolling summary coherent after 5+ turns? Run enough turns to trigger summarization and inspect the result.

**Step 2 — Iterate on prompts:**
- When a prompt produces bad output, modify `agents/prompts.py` and re-run. Keep prompts in one file so iteration is fast.
- Track what changes work. Common patterns: adding a concrete example, adding a "DO NOT" rule, removing ambiguous instructions.
- After each prompt change, re-run at least 3 turns to verify the fix doesn't break other turns.

**Step 3 — Capture as regression tests:**
- For each prompt issue discovered, save the failing model response as a fixture in `tests/fixtures/`.
- Write a test that parses the fixture through the agent's output parser and verifies the fix handles it. For example: if the narrator omits `responding_characters`, write `test_narrator_output_missing_characters()` that verifies the parser defaults to an empty list.
- For context assembly edge cases (e.g., conversation with 0 turns, memory with 0 facts, chapter with all beats hit), write unit tests that verify `build_*_messages()` produces valid output.

**Step 4 — Full integration re-test:**
- Run `uv run pytest tests/ -v` — all regression tests pass.
- Run `scripts/test_turn.py` again — 3 turns complete without errors.
- Verify git history is clean: `git log --oneline` in save dir shows expected commits.

---

## 11. Dependencies

### New Dependencies

None. This phase uses only packages already declared in Phases 01 and 02:

| Package | Used For |
|---|---|
| `pydantic` | Models (Phase 01) |
| `pyyaml` | YAML I/O (Phase 01) and structured output parsing (Phase 02) |
| `openai` | LLM calls via AsyncOpenAI (Phase 02) |
| `gitpython` | Save versioning (Phase 01) |
| `python-dotenv` | Environment variable loading |

### Standard Library

| Module | Used For |
|---|---|
| `asyncio` | Parallel post-turn processing (`asyncio.gather`) |
| `dataclasses` | `TurnResult`, `NarratorOutput`, etc. |
| `typing` | Type annotations |

No new packages are required for Phase 03.
