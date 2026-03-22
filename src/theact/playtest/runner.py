"""PlaytestRunner: orchestrates an automated playtest session."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from theact.engine.turn import run_turn
from theact.engine.types import TurnResult
from theact.io.save_manager import create_save, load_save
from theact.llm.call_log import LLMCallLog
from theact.playtest.config import PlaytestConfig
from theact.playtest.logger import PlaytestLogger, TurnLog
from theact.playtest.player_agent import PlayerAgent
from theact.playtest.report import (
    PlaytestReport,
    generate_report,
    write_report,
)
from theact.agents.prompts import MAX_KEY_FACTS
from theact.playtest.scoring import score_turn

logger = logging.getLogger(__name__)


class PlaytestRunner:
    """Runs a complete playtest session."""

    def __init__(self, config: PlaytestConfig) -> None:
        self.config = config
        self.logger = PlaytestLogger()
        self.call_log = LLMCallLog()
        self.player_agent = PlayerAgent(
            config.llm_config,
            edge_case_frequency=config.edge_case_frequency,
            direct_edge_case_frequency=config.direct_edge_case_frequency,
            nonsense_frequency=config.nonsense_frequency,
            repeat_frequency=config.repeat_frequency,
        )
        self._quality_scores: list[dict] = []

    async def run(
        self,
        on_turn_complete: Callable[[int, TurnLog, dict | None], None] | None = None,
    ) -> PlaytestReport:
        """Execute a full playtest. Returns a PlaytestReport.

        Args:
            on_turn_complete: Optional callback invoked after each turn completes.
                Receives (turn_number, turn_log, quality_score_dict). The quality
                score dict contains at minimum a "composite" key, or is None if
                scoring is unavailable. Used by the web UI for progress updates.
        """
        run_start = time.monotonic()

        # 1. Create a fresh save from the game definition
        save_id = f"playtest-{self.config.timestamp}"
        create_save(
            game_id=self.config.game_id,
            save_id=save_id,
            player_name=self.config.player_name,
        )

        # 2. Load the game
        game = load_save(save_id)
        self._game_title = game.meta.title

        # 2a. Run the opening narration (no player input)
        try:
            turn_start = time.monotonic()
            opening_result = await run_turn(
                game,
                player_input="",
                llm_config=self.config.llm_config,
                call_log=self.call_log,
                debug=self.config.debug,
            )
            self.logger.log_turn_result(
                0, opening_result, time.monotonic() - turn_start
            )
        except Exception as e:
            logger.warning("Opening narration failed: %s", e)
            self.logger.log_error(0, e)
            if self.config.stop_on_error:
                return self._finalize(run_start)

        # 3. Main turn loop
        for turn_num in range(1, self.config.max_turns + 1):
            turn_start = time.monotonic()

            try:
                # Get player input
                if turn_num == 1:
                    player_input = self.config.opening_action
                else:
                    current_chapter_id = game.state.current_chapter
                    chapter = game.chapters.get(current_chapter_id)
                    if chapter is None:
                        logger.warning(
                            "Chapter %s not found, stopping", current_chapter_id
                        )
                        break

                    player_input = await self.player_agent.decide(
                        conversation_tail=self.logger.recent_conversation(n=6),
                        chapter=chapter,
                        turn_number=turn_num,
                    )

                self.logger.log_player_input(turn_num, player_input)

                # Run the turn engine
                result = await run_turn(
                    game,
                    player_input,
                    llm_config=self.config.llm_config,
                    call_log=self.call_log,
                    debug=self.config.debug,
                )

                elapsed = time.monotonic() - turn_start

                # Detect issues BEFORE logging the turn result so that
                # is_repeating compares against prior turns, not the
                # current one. Then log the turn and attach the issues.
                detected_issues = self._detect_issues(turn_num, result)
                self.logger.log_turn_result(turn_num, result, elapsed)
                for issue in detected_issues:
                    self.logger.log_issue(turn_num, issue)

                # Compute quality score for this turn
                self._compute_quality_score(turn_num, result, game)

                # Invoke progress callback if provided
                if on_turn_complete is not None:
                    turn_log = self.logger.turns[-1] if self.logger.turns else None
                    quality_score = (
                        self._quality_scores[-1] if self._quality_scores else None
                    )
                    if turn_log is not None:
                        on_turn_complete(turn_num, turn_log, quality_score)

                # Check chapter completion
                if result.chapter_advanced:
                    self.logger.log_event(
                        turn_num, "chapter_completed", result.new_chapter or ""
                    )
                    if game.state.game_complete:
                        self.logger.log_event(turn_num, "game_over", "")
                        break

            except Exception as e:
                logger.warning("Turn %d failed: %s", turn_num, e)
                self.logger.log_error(turn_num, e)
                if self.config.stop_on_error:
                    break

            # Incremental save
            self.logger.flush_to_disk(self.config.output_dir, self.config.timestamp)

        return self._finalize(run_start)

    def _finalize(self, run_start: float) -> PlaytestReport:
        """Generate and write the final report."""
        total_duration = time.monotonic() - run_start

        # Collect final memory state
        memory_final: dict[str, str] = {}
        memory_final_facts: dict[str, list[str]] = {}
        if self.logger.turns:
            last_turn = self.logger.turns[-1]
            memory_final = dict(last_turn.memory_updates)
            memory_final_facts = dict(last_turn.memory_facts)

        report = generate_report(
            logger=self.logger,
            config=self.config,
            game_title=getattr(self, "_game_title", self.config.game_id),
            total_duration=total_duration,
            memory_final=memory_final,
            memory_final_facts=memory_final_facts,
            call_log=self.call_log,
            quality_scores=self._quality_scores,
        )

        write_report(report, self.logger, self.config)

        # Dump call log to YAML
        out_path = Path(self.config.output_dir) / self.config.timestamp
        out_path.mkdir(parents=True, exist_ok=True)
        self.call_log.dump_yaml(out_path / "llm_calls.yaml")

        return report

    def _compute_quality_score(
        self,
        turn_num: int,
        result: TurnResult,
        game: object,
    ) -> None:
        """Compute and store quality score for a turn."""
        from theact.models.game import LoadedGame

        if not isinstance(game, LoadedGame):
            return

        narration = result.narrator.narration if result.narrator else ""

        # Build parallel lists of character response texts and Character objects
        char_responses: list[str] = []
        char_objects: list[object] = []
        for cr in result.characters:
            char_responses.append(cr.response)
            # Find matching Character object by name
            for char in game.characters.values():
                if char.name == cr.character:
                    char_objects.append(char)
                    break

        # Collect memory update facts
        memory_facts: list[str] = []
        for diff in result.memory_diffs:
            memory_facts.extend(diff.new_facts)

        # Get issues for this turn from the logger
        yaml_issues: list[str] = []
        for t in self.logger.turns:
            if t.turn == turn_num:
                yaml_issues = t.issues
                break

        score = score_turn(
            narration=narration,
            character_responses=char_responses,
            characters=char_objects,  # type: ignore[arg-type]
            memory_updates=memory_facts,
            yaml_issues=yaml_issues,
        )

        self._quality_scores.append(
            {
                "turn": turn_num,
                "narration_length_ok": score.narration_length_ok,
                "yaml_first_attempt": score.yaml_first_attempt,
                "character_personality": score.character_personality,
                "memory_relevance": score.memory_relevance,
                "composite": score.composite,
            }
        )

    def _detect_issues(self, turn: int, result: TurnResult) -> list[str]:
        """Detect common problems. Returns a list of issue strings.

        Must be called BEFORE log_turn_result so that is_repeating
        compares against prior turns rather than the current one.
        """
        issues: list[str] = []

        # Empty narrator response
        if not result.narrator.narration.strip():
            issues.append("empty_narrator_response")

        # Empty character responses
        for cr in result.characters:
            if not cr.response.strip():
                issues.append(f"empty_character_response:{cr.character}")

        # Repeated content (stuck loop detection)
        if self.logger.is_repeating(result.narrator.narration, window=3):
            issues.append("narrator_repeating")

        # Memory overflow -- facts exceeding MAX_KEY_FACTS (truncated by parser)
        for diff in result.memory_diffs:
            if len(diff.new_facts) > MAX_KEY_FACTS:
                issues.append(f"memory_overflow:{diff.character}")

        # Fact-summary overlap -- facts that repeat what's in the summary
        for diff in result.memory_diffs:
            if not diff.new_summary or not diff.new_facts:
                continue
            summary_words = {
                w.strip(".,;:!?\"'()")
                for w in diff.new_summary.lower().split()
                if len(w) > 3
            }
            for fact in diff.new_facts:
                fact_words = [
                    w.strip(".,;:!?\"'()") for w in fact.lower().split() if len(w) > 3
                ]
                if (
                    fact_words
                    and sum(1 for w in fact_words if w in summary_words)
                    / len(fact_words)
                    > 0.7
                ):
                    char_id = diff.character.lower().replace(" ", "_")
                    issues.append(f"memory_fact_overlap:{char_id}")
                    break  # one flag per character is enough

        # Stale facts -- facts unchanged from previous turn
        if self.logger.turns:
            prev_turn = self.logger.turns[-1]
            for diff in result.memory_diffs:
                prev_facts = prev_turn.memory_facts.get(diff.character, [])
                if prev_facts and prev_facts == diff.new_facts:
                    char_id = diff.character.lower().replace(" ", "_")
                    issues.append(f"memory_stale:{char_id}")

        return issues
