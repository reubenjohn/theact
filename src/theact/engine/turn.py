"""Turn engine orchestrator: executes a complete game turn.

This is the core of TheAct. Each call to run_turn():
1. Runs the narrator agent (streaming)
2. Runs character agents sequentially (streaming)
3. Runs post-turn agents in parallel (memory update, game state check)
4. Handles chapter advancement and rolling summarization
5. Persists all changes to disk and commits via git
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable

from theact.agents.character import run_character
from theact.agents.game_state import run_game_state
from theact.agents.memory import run_memory_update
from theact.agents.narrator import run_narrator
from theact.agents.summarizer import run_chapter_summary, run_rolling_summary
from theact.engine.context import (
    build_character_messages,
    build_game_state_messages,
    build_memory_messages,
    build_narrator_messages,
)
from theact.engine.diagnostics import DiagnosticsWriter
from theact.engine.types import (
    CharacterResponse,
    GameStateResult,
    MemoryDiff,
    NarratorOutput,
    TurnResult,
)
from theact.io.save_manager import (
    append_conversation,
    save_memory,
    save_state,
    save_summaries,
)
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.llm.config import LLMConfig
from theact.llm.tokens import estimate_tokens
from theact.models.chapter import ChapterSummary
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame
from theact.models.memory import CharacterMemory
from theact.versioning.git_save import commit_turn

logger = logging.getLogger(__name__)

# Callback type for streaming output to the UI.
# (source: "narrator"|"character", character_name: str | None, token: str,
#  is_thinking: bool)
StreamCallback = Callable[[str, str | None, str, bool], Awaitable[None]]

# ---------------------------------------------------------------------------
# Normalization helpers for small-model output
# ---------------------------------------------------------------------------

# Rolling summary triggers when unsummarized conversation exceeds this budget.
SUMMARY_THRESHOLD_TOKENS = 1500
# Number of recent turns to keep verbatim (not summarized).
KEEP_RECENT_TURNS = 4

_STRIP_RE = re.compile(r"[^\w\s]")


def _normalize_text(text: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    return _STRIP_RE.sub("", text.lower()).strip()


def _word_set(text: str) -> set[str]:
    """Return the set of meaningful words (len > 2) from normalized text."""
    return {w for w in _normalize_text(text).split() if len(w) > 2}


def resolve_beat(model_beat: str, canonical_beats: list[str]) -> str | None:
    """Match a model-returned beat to a canonical beat from the chapter.

    Returns the canonical beat text if a match is found, None otherwise.
    Uses tight constraints: ≥60% word overlap with the best candidate.
    """
    stripped = model_beat.strip().strip("\"'")
    # 1. Exact match
    for cb in canonical_beats:
        if stripped == cb:
            return cb
    # 2. Case-insensitive match
    for cb in canonical_beats:
        if stripped.lower() == cb.lower():
            return cb
    # 3. Fuzzy word-overlap match
    model_words = _word_set(stripped)
    if not model_words:
        return None
    best_score = 0.0
    best_beat: str | None = None
    for cb in canonical_beats:
        canon_words = _word_set(cb)
        if not canon_words:
            continue
        overlap = len(model_words & canon_words)
        shorter = min(len(model_words), len(canon_words))
        score = overlap / shorter if shorter else 0.0
        if score > best_score:
            best_score = score
            best_beat = cb
    if best_score >= 0.6 and best_beat is not None:
        return best_beat
    return None


def resolve_character_id(model_id: str, characters: dict[str, object]) -> str | None:
    """Resolve a model-returned character identifier to a canonical ID.

    Tries: exact → case-insensitive → name match → partial match.
    Returns the canonical character ID or None.
    """
    if not model_id or not model_id.strip():
        return None
    # 1. Exact match
    if model_id in characters:
        return model_id
    # 2. Case-insensitive ID match
    lower_map = {cid.lower(): cid for cid in characters}
    if model_id.lower() in lower_map:
        return lower_map[model_id.lower()]
    # 3. Match against character display names
    for cid, char in characters.items():
        name = getattr(char, "name", "")
        if name and name.lower() == model_id.lower():
            return cid
    # 4. Partial / slug match (e.g. "maya_chen" → "maya")
    model_slug = model_id.lower().replace(" ", "_").replace("-", "_")
    for cid in characters:
        if model_slug.startswith(cid.lower()) or cid.lower().startswith(model_slug):
            return cid
    return None


NarratorDoneCallback = Callable[[NarratorOutput], Awaitable[None]]


async def run_turn(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
    on_narrator_done: NarratorDoneCallback | None = None,
    call_log: LLMCallLog | None = None,
    debug: bool = False,
) -> TurnResult:
    """Execute a complete turn.

    Args:
        game: The fully loaded game state.
        player_input: The player's typed input.
        llm_config: LLM configuration.
        on_token: Optional callback for streaming tokens to the UI.
            Called as: await on_token(source, character_name, token_text)
        on_narrator_done: Optional callback fired after narrator parsing,
            before character agents start. Receives the parsed NarratorOutput.

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
    diag = DiagnosticsWriter(game.save_path, new_turn) if debug else None
    diag_records: list[LLMCallRecord] = []

    # -- Step 1: Narrator ------------------------------------------------

    if diag:
        narrator_msgs = build_narrator_messages(game, player_input, llm_config)

    # Reset chapter transition flag after narrator messages are built
    # (must happen after build_narrator_messages reads it, but before run_narrator)
    game.state.chapter_just_advanced = False

    async def narrator_token_cb(token: str, is_thinking: bool) -> None:
        if on_token:
            await on_token("narrator", None, token, is_thinking)

    log_before = len(call_log.records) if call_log else 0
    narrator_output = await run_narrator(
        game,
        player_input,
        llm_config,
        narrator_token_cb,
        call_log=call_log,
        turn=new_turn,
    )
    if diag and call_log and len(call_log.records) > log_before:
        rec = call_log.records[-1]
        diag_records.append(rec)
        diag.write_agent(
            "narrator",
            narrator_msgs,
            narrator_output.narration,
            parsed_data={
                "narration": narrator_output.narration,
                "responding_characters": narrator_output.responding_characters,
                "mood": narrator_output.mood,
            },
            call_record=rec,
        )

    # Record narrator entry, then player entry
    entries.append(
        ConversationEntry(
            turn=new_turn, role="narrator", content=narrator_output.narration
        )
    )
    entries.append(
        ConversationEntry(turn=new_turn, role="player", content=player_input)
    )

    if on_narrator_done:
        await on_narrator_done(narrator_output)

    # -- Step 2: Character agents (sequential) ---------------------------

    character_responses: list[CharacterResponse] = []
    prior_responses: list[CharacterResponse] = []
    seen_char_ids: set[str] = set()

    for raw_char_id in narrator_output.responding_characters:
        char_id = resolve_character_id(raw_char_id, game.characters)
        if char_id is None:
            logger.warning(
                "Narrator returned unknown character id: %s — skipping", raw_char_id
            )
            continue
        if char_id != raw_char_id:
            logger.info("Resolved character id %r → %r", raw_char_id, char_id)
        if char_id in seen_char_ids:
            continue
        seen_char_ids.add(char_id)

        char = game.characters[char_id]
        char_memory = game.memories.get(char_id)

        if diag:
            char_msgs = build_character_messages(
                game,
                char,
                char_memory,
                player_input,
                narrator_output,
                prior_responses,
                llm_config,
            )

        async def char_token_cb(
            token: str, is_thinking: bool, _name: str = char.name
        ) -> None:
            if on_token:
                await on_token("character", _name, token, is_thinking)

        log_before_char = len(call_log.records) if call_log else 0
        response = await run_character(
            game=game,
            character=char,
            memory=char_memory,
            player_input=player_input,
            narrator_output=narrator_output,
            prior_responses=prior_responses,
            llm_config=llm_config,
            on_token=char_token_cb,
            call_log=call_log,
            turn=new_turn,
        )
        if diag and call_log and len(call_log.records) > log_before_char:
            rec = call_log.records[-1]
            diag_records.append(rec)
            diag.write_agent(
                f"character-{char_id}",
                char_msgs,
                response.response,
                call_record=rec,
            )

        character_responses.append(response)
        prior_responses.append(response)

        entries.append(
            ConversationEntry(
                turn=new_turn,
                role="character",
                character=char.name,
                content=response.response,
            )
        )

    # -- Step 3: Post-turn agents (parallel) -----------------------------
    # Reuse the already-resolved character IDs from step 2

    memory_tasks = []
    memory_char_ids: list[str] = []
    diag_memory_msgs: dict[str, list[dict]] = {}
    for char_id in seen_char_ids:
        char = game.characters[char_id]
        char_memory = game.memories.get(char_id)
        if diag:
            diag_memory_msgs[char_id] = build_memory_messages(
                char, char_memory, entries
            )
        memory_tasks.append(
            run_memory_update(
                char,
                char_memory,
                entries,
                llm_config,
                call_log=call_log,
                turn=new_turn,
            )
        )
        memory_char_ids.append(char_id)

    if diag:
        diag_state_msgs = build_game_state_messages(game, entries)

    log_before_post = len(call_log.records) if call_log else 0
    state_task = run_game_state(
        game, entries, llm_config, call_log=call_log, turn=new_turn
    )

    all_results = await asyncio.gather(
        *memory_tasks,
        state_task,
        return_exceptions=True,
    )

    # Unpack memory results (all except last), keeping char_id paired with diff
    successful_memory: list[tuple[str, MemoryDiff]] = []
    for char_id, result in zip(memory_char_ids, all_results[:-1]):
        if isinstance(result, Exception):
            logger.warning(
                "Memory update agent failed: %s: %s",
                type(result).__name__,
                result,
            )
            continue
        successful_memory.append((char_id, result))

    # Unpack game state result (last)
    state_result = all_results[-1]
    if isinstance(state_result, Exception):
        logger.warning(
            "Game state agent failed: %s: %s",
            type(state_result).__name__,
            state_result,
        )
        state_result = GameStateResult(beats_hit=[], completed=False)

    # Write diagnostics for post-turn agents
    if diag and call_log:
        post_records = call_log.records[log_before_post:]
        for rec in post_records:
            diag_records.append(rec)
            if rec.agent.startswith("memory:"):
                cid = rec.agent.split(":", 1)[1]
                msgs = diag_memory_msgs.get(cid, [])
                diag.write_agent(
                    f"memory-{cid}",
                    msgs,
                    "",
                    call_record=rec,
                )
            elif rec.agent == "game_state":
                diag.write_agent(
                    "game_state",
                    diag_state_msgs,
                    "",
                    parsed_data={
                        "beats_hit": state_result.beats_hit,
                        "completed": state_result.completed,
                        "reasoning": state_result.reasoning,
                    },
                    call_record=rec,
                )

    # -- Step 4: Apply changes -------------------------------------------

    game.state.turn = new_turn

    # Apply memory diffs
    for char_id, diff in successful_memory:
        _apply_memory_diff(game, char_id, diff)

    # Record newly hit beats (fuzzy-match against chapter definition)
    current_chapter = game.chapters.get(game.state.current_chapter)
    canonical_beats = current_chapter.beats if current_chapter else []
    for beat in state_result.beats_hit:
        resolved = resolve_beat(beat, canonical_beats)
        if resolved is None:
            logger.warning("Game state returned unrecognized beat: %r — ignoring", beat)
            continue
        if resolved != beat:
            logger.info("Resolved beat %r → %r", beat, resolved)
        if resolved not in game.state.beats_hit:
            game.state.beats_hit.append(resolved)

    # Append all conversation entries
    for entry in entries:
        game.conversation.append(entry)
        append_conversation(game.save_path, entry)

    # -- Step 5: Chapter advancement -------------------------------------

    chapter_advanced = False
    new_chapter = None

    if state_result.completed and not game.state.game_complete:
        chapter_advanced, new_chapter = await _advance_chapter(
            game, llm_config, call_log=call_log, turn=new_turn
        )

    # -- Step 6: Rolling summary (if needed) -----------------------------

    summary_updated = await _maybe_update_rolling_summary(
        game, llm_config, call_log=call_log, turn=new_turn
    )

    # -- Write diagnostics summary (if debug) ----------------------------

    if diag and diag_records:
        diag.write_summary(diag_records)

    # -- Step 7: Persist + Git commit ------------------------------------

    save_state(game.save_path, game.state)
    for char_id in memory_char_ids:
        if char_id in game.memories:
            save_memory(game.save_path, game.memories[char_id])

    commit_summary = narrator_output.narration[:60].replace("\n", " ")
    commit_turn(game.save_path, new_turn, commit_summary)

    return TurnResult(
        turn=new_turn,
        narrator=narrator_output,
        characters=character_responses,
        memory_diffs=[diff for _, diff in successful_memory],
        game_state=state_result,
        chapter_advanced=chapter_advanced,
        new_chapter=new_chapter,
        summary_updated=summary_updated,
    )


def _apply_memory_diff(game: LoadedGame, char_id: str, diff: MemoryDiff) -> None:
    """Apply a MemoryDiff to the in-memory game state.

    The MemoryDiff already contains the new summary and new facts list
    (computed by the memory agent). We simply replace the character's
    memory with the new values.
    """
    if char_id not in game.memories:
        char_name = (
            game.characters[char_id].name
            if char_id in game.characters
            else diff.character
        )
        game.memories[char_id] = CharacterMemory(
            character=char_name,
            summary="",
            key_facts=[],
        )

    mem = game.memories[char_id]
    mem.summary = diff.new_summary
    mem.key_facts = list(diff.new_facts)


async def _advance_chapter(
    game: LoadedGame,
    llm_config: LLMConfig,
    call_log: LLMCallLog | None = None,
    turn: int = 0,
) -> tuple[bool, str | None]:
    """Handle chapter completion: generate summary, advance state."""
    current = game.chapters.get(game.state.current_chapter)
    if not current or not current.next:
        # Final chapter -- mark the game as complete
        if current:
            game.state.game_complete = True
        return False, None

    # Generate chapter summary via summarizer
    chapter_summary_text = await run_chapter_summary(
        game, current, llm_config, call_log=call_log, turn=turn
    )

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

    return True, current.next


async def _maybe_update_rolling_summary(
    game: LoadedGame,
    llm_config: LLMConfig,
    call_log: LLMCallLog | None = None,
    turn: int = 0,
) -> bool:
    """Trigger rolling summarization if conversation exceeds token budget.

    Only counts entries added since the last summarization to avoid
    triggering on every turn after the first summary.

    Returns True if the summary was updated.
    """
    # Only count entries added since the last summarization
    new_entries = [
        e for e in game.conversation if e.turn > game.state.last_summarized_turn
    ]
    conv_text = "\n".join(e.content for e in new_entries)
    conv_tokens = estimate_tokens(conv_text)

    if conv_tokens <= SUMMARY_THRESHOLD_TOKENS:
        return False

    # Find the cutoff: keep the last KEEP_RECENT_TURNS turns
    turns_seen: set[int] = set()
    cutoff_idx = len(game.conversation)
    for i in range(len(game.conversation) - 1, -1, -1):
        t = game.conversation[i].turn
        turns_seen.add(t)
        if len(turns_seen) > KEEP_RECENT_TURNS:
            cutoff_idx = i + 1
            break

    if cutoff_idx <= 0:
        return False

    # The entries to summarize
    old_entries = game.conversation[:cutoff_idx]

    new_summary = await run_rolling_summary(
        game.state.rolling_summary,
        old_entries,
        llm_config,
        call_log=call_log,
        turn=turn,
    )

    game.state.rolling_summary = new_summary

    # Record which turn we summarized up to
    cutoff_turn = max(e.turn for e in old_entries)
    game.state.last_summarized_turn = cutoff_turn
    return True
