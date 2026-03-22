"""Playtest logger: captures all data from a playtest run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from theact.engine.types import TurnResult
from theact.models.conversation import ConversationEntry


@dataclass
class TurnLog:
    """Everything captured for a single turn."""

    turn: int
    player_input: str = ""
    narrator_text: str = ""
    narrator_thinking: str = ""
    character_texts: dict[str, str] = field(default_factory=dict)
    character_thinking: dict[str, str] = field(default_factory=dict)
    characters_responded: list[str] = field(default_factory=list)
    memory_updates: dict[str, str] = field(default_factory=dict)
    memory_facts: dict[str, list[str]] = field(default_factory=dict)
    memory_thinking: dict[str, str] = field(default_factory=dict)
    game_state_thinking: str = ""
    beats_hit: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    issues: list[str] = field(default_factory=list)
    is_edge_case: bool = False
    prompt_tokens: int = 0
    thinking_tokens: int = 0
    response_tokens: int = 0


class PlaytestLogger:
    """Accumulates all playtest data for report generation."""

    def __init__(self) -> None:
        self.turns: list[TurnLog] = []
        self.errors: list[tuple[int, str]] = []  # (turn, error message)
        self.events: list[tuple[int, str, str]] = []  # (turn, event, detail)
        self._pending_input: dict[int, str] = {}  # turn -> player_input

    def log_player_input(self, turn: int, text: str) -> None:
        """Record what the player typed for a given turn."""
        self._pending_input[turn] = text

    def log_turn_result(self, turn: int, result: TurnResult, elapsed: float) -> None:
        """Record the full result of a turn."""
        player_input = self._pending_input.pop(turn, "")

        char_texts: dict[str, str] = {}
        char_thinking: dict[str, str] = {}
        chars_responded: list[str] = []

        for cr in result.characters:
            char_texts[cr.character] = cr.response
            if cr.thinking:
                char_thinking[cr.character] = cr.thinking
            chars_responded.append(cr.character)

        memory_updates: dict[str, str] = {}
        memory_facts: dict[str, list[str]] = {}
        for diff in result.memory_diffs:
            memory_updates[diff.character] = diff.new_summary
            memory_facts[diff.character] = list(diff.new_facts)

        beats_hit: list[str] = []
        if result.game_state:
            beats_hit = list(result.game_state.beats_hit)

        log = TurnLog(
            turn=turn,
            player_input=player_input,
            narrator_text=result.narrator.narration if result.narrator else "",
            character_texts=char_texts,
            character_thinking=char_thinking,
            characters_responded=chars_responded,
            memory_updates=memory_updates,
            memory_facts=memory_facts,
            beats_hit=beats_hit,
            elapsed_seconds=elapsed,
        )
        self.turns.append(log)

    def log_error(self, turn: int, error: Exception) -> None:
        """Record an error that occurred during a turn."""
        self.errors.append((turn, f"{type(error).__name__}: {error}"))

    def log_issue(self, turn: int, issue: str) -> None:
        """Record a detected issue (not an exception, but a quality problem)."""
        # Find the turn log and append the issue
        for t in self.turns:
            if t.turn == turn:
                t.issues.append(issue)
                return
        # If turn not yet logged, create a minimal entry
        self.events.append((turn, "issue", issue))

    def log_event(self, turn: int, event: str, detail: str) -> None:
        """Record a notable event (chapter completion, game over, etc.)."""
        self.events.append((turn, event, detail))

    def recent_conversation(self, n: int = 6) -> list[ConversationEntry]:
        """Return the last N conversation entries for the player agent.

        Constructs ConversationEntry objects from the logged turn data.
        """
        entries: list[ConversationEntry] = []
        for t in self.turns:
            if t.narrator_text:
                entries.append(
                    ConversationEntry(
                        turn=t.turn, role="narrator", content=t.narrator_text
                    )
                )
            if t.player_input:
                entries.append(
                    ConversationEntry(
                        turn=t.turn, role="player", content=t.player_input
                    )
                )
            for char_name, text in t.character_texts.items():
                entries.append(
                    ConversationEntry(
                        turn=t.turn,
                        role="character",
                        character=char_name,
                        content=text,
                    )
                )
        return entries[-n:]

    def is_repeating(self, text: str, window: int = 3) -> bool:
        """Check if the narrator output is too similar to recent turns.

        Uses word-set overlap: computes the set of words in the new text
        and each recent narrator text, then flags as repeating if the
        Jaccard similarity exceeds 0.6 (60% word overlap). This is more
        robust than prefix matching, which gives false positives when
        many narrator responses start with 'You' or 'The'.
        """
        new_words = set(text.lower().split())
        for turn_log in self.turns[-window:]:
            old_words = set(turn_log.narrator_text.lower().split())
            if not new_words or not old_words:
                continue
            overlap = len(new_words & old_words) / len(new_words | old_words)
            if overlap > 0.6:
                return True
        return False

    def flush_to_disk(self, output_dir: str, timestamp: str) -> None:
        """Write current logger state to disk incrementally.

        Called after each turn so data survives process crashes. Writes
        conversation.yaml and errors.yaml to the timestamped output
        directory. The final report.md is only written at the end, but
        the raw data files are always up-to-date on disk.
        """
        out_path = Path(output_dir) / timestamp
        out_path.mkdir(parents=True, exist_ok=True)

        # Write conversation data
        conversation_data = []
        for t in self.turns:
            turn_data: dict = {
                "turn": t.turn,
                "player_input": t.player_input,
                "narrator_text": t.narrator_text,
                "characters_responded": t.characters_responded,
                "character_texts": t.character_texts,
                "beats_hit": t.beats_hit,
                "elapsed_seconds": round(t.elapsed_seconds, 2),
                "issues": t.issues,
            }
            if t.memory_updates or t.memory_facts:
                turn_data["memory_updates"] = {
                    char: {
                        "summary": t.memory_updates.get(char, ""),
                        "facts": t.memory_facts.get(char, []),
                    }
                    for char in set(t.memory_updates) | set(t.memory_facts)
                }
            conversation_data.append(turn_data)

        with open(out_path / "conversation.yaml", "w") as f:
            yaml.dump(
                conversation_data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

        # Write errors
        if self.errors:
            error_data = [{"turn": turn, "error": msg} for turn, msg in self.errors]
            with open(out_path / "errors.yaml", "w") as f:
                yaml.dump(
                    error_data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

        # Write timing data
        timing_data = [
            {"turn": t.turn, "elapsed_seconds": round(t.elapsed_seconds, 2)}
            for t in self.turns
        ]
        with open(out_path / "timing.yaml", "w") as f:
            yaml.dump(
                timing_data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    def all_issues(self) -> list[tuple[int, str]]:
        """Return all issues across all turns as (turn, issue) pairs."""
        result: list[tuple[int, str]] = []
        for t in self.turns:
            for issue in t.issues:
                result.append((t.turn, issue))
        return result
