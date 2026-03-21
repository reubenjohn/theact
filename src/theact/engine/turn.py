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
    TurnResult,
)
from theact.io.save_manager import (
    append_conversation,
    save_memory,
    save_state,
    save_summaries,
)
from theact.llm.call_log import LLMCallLog
from theact.llm.config import LLMConfig
from theact.llm.tokens import estimate_tokens
from theact.models.chapter import ChapterSummary
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame
from theact.models.memory import CharacterMemory
from theact.versioning.git_save import commit_turn

logger = logging.getLogger(__name__)

# Callback type for streaming output to the UI.
# (source: "narrator"|"character", character_name: str | None, token: str)
StreamCallback = Callable[[str, str | None, str], Awaitable[None]]


async def run_turn(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
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
    diag_records: list = []

    # -- Step 1: Narrator ------------------------------------------------

    if diag:
        narrator_msgs = build_narrator_messages(game, player_input, llm_config)

    async def narrator_token_cb(token: str) -> None:
        if on_token:
            await on_token("narrator", None, token)

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

    # -- Step 2: Character agents (sequential) ---------------------------

    character_responses: list[CharacterResponse] = []
    prior_responses: list[CharacterResponse] = []

    for char_id in narrator_output.responding_characters:
        if char_id not in game.characters:
            logger.warning(
                "Narrator returned unknown character id: %s — skipping", char_id
            )
            continue

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

        async def char_token_cb(token: str, _name: str = char.name) -> None:
            if on_token:
                await on_token("character", _name, token)

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

    memory_tasks = []
    memory_char_ids: list[str] = []
    diag_memory_msgs: dict[str, list[dict]] = {}
    for char_id in narrator_output.responding_characters:
        if char_id not in game.characters:
            continue
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

    # Unpack memory results (all except last)
    memory_diffs: list[MemoryDiff] = []
    for result in all_results[:-1]:
        if isinstance(result, Exception):
            logger.warning(
                "Memory update agent failed: %s: %s",
                type(result).__name__,
                result,
            )
            continue
        memory_diffs.append(result)

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
    for i, diff in enumerate(memory_diffs):
        char_id = memory_char_ids[i] if i < len(memory_char_ids) else None
        if char_id:
            _apply_memory_diff(game, char_id, diff)

    # Record newly hit beats
    for beat in state_result.beats_hit:
        if beat not in game.state.beats_hit:
            game.state.beats_hit.append(beat)

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

    await _maybe_update_rolling_summary(
        game, llm_config, call_log=call_log, turn=new_turn
    )

    # -- Write diagnostics summary (if debug) ----------------------------

    if diag and diag_records:
        diag.write_summary(diag_records)

    # -- Step 7: Persist + Git commit ------------------------------------

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
        chapter_advanced=chapter_advanced,
        new_chapter=new_chapter,
        summary_updated=False,
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
) -> None:
    """Trigger rolling summarization if conversation exceeds token budget.

    Only counts entries added since the last summarization to avoid
    triggering on every turn after the first summary.
    """
    SUMMARY_THRESHOLD = 1500  # tokens of unsummarized conversation
    KEEP_RECENT = 4  # number of recent turns to keep verbatim

    # Only count entries added since the last summarization
    new_entries = [
        e for e in game.conversation if e.turn > game.state.last_summarized_turn
    ]
    conv_text = "\n".join(e.content for e in new_entries)
    conv_tokens = estimate_tokens(conv_text)

    if conv_tokens <= SUMMARY_THRESHOLD:
        return

    # Find the cutoff: keep the last KEEP_RECENT turns
    turns_seen: list[int] = []
    cutoff_idx = len(game.conversation)
    for i in range(len(game.conversation) - 1, -1, -1):
        t = game.conversation[i].turn
        if t not in turns_seen:
            turns_seen.append(t)
        if len(turns_seen) > KEEP_RECENT:
            cutoff_idx = i + 1
            break

    if cutoff_idx <= 0:
        return

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
