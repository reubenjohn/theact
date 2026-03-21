"""PlaytestRunner: orchestrates an automated playtest session."""

from __future__ import annotations

import logging
import time

from theact.engine.turn import run_turn
from theact.engine.types import TurnResult
from theact.io.save_manager import create_save, load_save
from theact.playtest.config import PlaytestConfig
from theact.playtest.logger import PlaytestLogger
from theact.playtest.player_agent import PlayerAgent
from theact.playtest.report import (
    PlaytestReport,
    generate_report,
    write_report,
)

logger = logging.getLogger(__name__)


class PlaytestRunner:
    """Runs a complete playtest session."""

    def __init__(self, config: PlaytestConfig) -> None:
        self.config = config
        self.logger = PlaytestLogger()
        self.player_agent = PlayerAgent(
            config.llm_config,
            edge_case_frequency=config.edge_case_frequency,
        )

    async def run(self) -> PlaytestReport:
        """Execute a full playtest. Returns a PlaytestReport."""
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

        # 2a. Run the opening narration (no player input)
        try:
            turn_start = time.monotonic()
            opening_result = await run_turn(
                game, player_input="", llm_config=self.config.llm_config
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
                    game, player_input, llm_config=self.config.llm_config
                )

                elapsed = time.monotonic() - turn_start

                # Detect issues BEFORE logging the turn result so that
                # is_repeating compares against prior turns, not the
                # current one. Then log the turn and attach the issues.
                detected_issues = self._detect_issues(turn_num, result)
                self.logger.log_turn_result(turn_num, result, elapsed)
                for issue in detected_issues:
                    self.logger.log_issue(turn_num, issue)

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
        if self.logger.turns:
            last_turn = self.logger.turns[-1]
            memory_final = dict(last_turn.memory_updates)

        report = generate_report(
            logger=self.logger,
            config=self.config,
            game_title=self.config.game_id,
            total_duration=total_duration,
            memory_final=memory_final,
        )

        write_report(report, self.logger, self.config)
        return report

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

        # Memory overflow -- key_facts exceeding limit (max 10 per CLAUDE.md)
        for diff in result.memory_diffs:
            if len(diff.new_facts) > 10:
                issues.append(f"memory_overflow:{diff.character}")

        return issues
