"""Tests for playtest report generation — covers _compute_memory_health,
generate_report, generate_report_markdown, and write_report."""

from __future__ import annotations

from pathlib import Path

import yaml

from theact.engine.types import (
    CharacterResponse,
    GameStateResult,
    MemoryDiff,
    NarratorOutput,
    TurnResult,
)
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.playtest.config import PlaytestConfig
from theact.playtest.logger import PlaytestLogger
from theact.playtest.report import (
    PlaytestReport,
    _compute_memory_health,
    generate_report,
    generate_report_markdown,
    write_report,
)


# -- Helpers ---------------------------------------------------------------


def _make_turn_result(
    turn: int = 1,
    narration: str = "You see the beach.",
    characters: list[CharacterResponse] | None = None,
    memory_diffs: list[MemoryDiff] | None = None,
    beats_hit: list[str] | None = None,
    completed: bool = False,
) -> TurnResult:
    return TurnResult(
        turn=turn,
        narrator=NarratorOutput(
            narration=narration,
            responding_characters=["maya"] if characters else [],
            mood="tense",
        ),
        characters=characters or [],
        memory_diffs=memory_diffs or [],
        game_state=GameStateResult(
            beats_hit=beats_hit or [],
            completed=completed,
        ),
    )


def _make_config(tmp_path: Path | None = None, **kwargs) -> PlaytestConfig:
    defaults = dict(
        game_id="test-game",
        max_turns=10,
        timestamp="2026-01-01T00-00-00",
    )
    if tmp_path is not None:
        defaults["output_dir"] = str(tmp_path / "reports")
    defaults.update(kwargs)
    return PlaytestConfig(**defaults)


def _build_logger_with_memory(
    facts_per_turn: list[dict[str, list[str]]],
    summaries_per_turn: list[dict[str, str]] | None = None,
) -> PlaytestLogger:
    """Build a PlaytestLogger whose turns have pre-set memory_facts and memory_updates."""
    logger = PlaytestLogger()
    for i, facts_dict in enumerate(facts_per_turn):
        turn_num = i + 1
        result = _make_turn_result(turn=turn_num)
        logger.log_turn_result(turn_num, result, 1.0)
        # Patch in memory data directly
        t = logger.turns[-1]
        t.memory_facts = facts_dict
        if summaries_per_turn:
            t.memory_updates = summaries_per_turn[i]
        else:
            t.memory_updates = {char: "" for char in facts_dict}
    return logger


# -- _compute_memory_health ------------------------------------------------


class TestComputeMemoryHealth:
    def test_empty_logger(self):
        logger = PlaytestLogger()
        health = _compute_memory_health(logger)
        assert health["turns_with_memory"] == 0
        assert health["per_character"] == {}

    def test_single_character_basic_stats(self):
        logger = _build_logger_with_memory(
            facts_per_turn=[
                {"Maya": ["fact1", "fact2"]},
                {"Maya": ["fact1", "fact2", "fact3"]},
            ]
        )
        health = _compute_memory_health(logger)
        assert health["turns_with_memory"] == 2
        maya = health["per_character"]["Maya"]
        assert maya["avg_fact_count"] == 2.5
        assert maya["max_fact_count"] == 3
        assert maya["total_turns"] == 2

    def test_at_cap_detection(self):
        """Facts at MAX_KEY_FACTS (5) should be flagged."""
        from theact.agents.prompts import MAX_KEY_FACTS

        logger = _build_logger_with_memory(
            facts_per_turn=[
                {"Maya": [f"fact{i}" for i in range(MAX_KEY_FACTS)]},
                {"Maya": [f"fact{i}" for i in range(3)]},
            ]
        )
        health = _compute_memory_health(logger)
        maya = health["per_character"]["Maya"]
        assert maya["turns_at_cap"] == 1

    def test_stale_facts_detection(self):
        """Identical facts across consecutive turns count as stale."""
        same_facts = ["The player found a key", "Maya is suspicious"]
        logger = _build_logger_with_memory(
            facts_per_turn=[
                {"Maya": same_facts},
                {"Maya": same_facts},  # stale
                {"Maya": ["Something new"]},  # not stale
                {"Maya": ["Something new"]},  # stale again
            ]
        )
        health = _compute_memory_health(logger)
        maya = health["per_character"]["Maya"]
        assert maya["turns_stale"] == 2

    def test_overlap_detection(self):
        """Facts whose words overlap >70% with the summary get flagged."""
        logger = _build_logger_with_memory(
            facts_per_turn=[
                {"Maya": ["Maya found the ancient golden artifact hidden inside"]},
            ],
            summaries_per_turn=[
                {
                    "Maya": "Maya found the ancient golden artifact hidden inside the cave"
                },
            ],
        )
        health = _compute_memory_health(logger)
        maya = health["per_character"]["Maya"]
        assert maya["turns_with_overlap"] == 1

    def test_no_overlap_when_no_summary(self):
        logger = _build_logger_with_memory(
            facts_per_turn=[
                {"Maya": ["Maya found the artifact"]},
            ],
            summaries_per_turn=[
                {"Maya": ""},
            ],
        )
        health = _compute_memory_health(logger)
        maya = health["per_character"]["Maya"]
        assert maya["turns_with_overlap"] == 0

    def test_multiple_characters(self):
        logger = _build_logger_with_memory(
            facts_per_turn=[
                {"Maya": ["f1"], "Joaquin": ["j1", "j2"]},
                {"Maya": ["f1", "f2"], "Joaquin": ["j3"]},
            ]
        )
        health = _compute_memory_health(logger)
        assert "Maya" in health["per_character"]
        assert "Joaquin" in health["per_character"]
        assert health["per_character"]["Maya"]["total_turns"] == 2
        assert health["per_character"]["Joaquin"]["total_turns"] == 2

    def test_turns_without_memory_skipped(self):
        logger = PlaytestLogger()
        # Turn 1: has memory
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)
        logger.turns[-1].memory_facts = {"Maya": ["fact1"]}
        logger.turns[-1].memory_updates = {"Maya": ""}
        # Turn 2: no memory
        r2 = _make_turn_result(turn=2)
        logger.log_turn_result(2, r2, 1.0)
        # memory_facts stays empty
        health = _compute_memory_health(logger)
        assert health["turns_with_memory"] == 1


# -- generate_report -------------------------------------------------------


class TestGenerateReportExtended:
    def test_character_response_rate(self):
        logger = PlaytestLogger()
        # Turn 1: characters responded
        r1 = _make_turn_result(
            turn=1,
            characters=[CharacterResponse(character="Maya", response="Hi")],
        )
        logger.log_turn_result(1, r1, 2.0)
        # Turn 2: no characters
        r2 = _make_turn_result(turn=2)
        logger.log_turn_result(2, r2, 3.0)

        config = _make_config()
        report = generate_report(logger, config, "Test", 5.0)
        assert report.character_response_rate == 0.5

    def test_yaml_parse_success_rate(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)
        logger.log_issue(1, "yaml_parse_error")
        r2 = _make_turn_result(turn=2)
        logger.log_turn_result(2, r2, 1.0)

        config = _make_config()
        report = generate_report(logger, config, "Test", 2.0)
        assert report.yaml_parse_success_rate == 0.5

    def test_zero_elapsed_excluded_from_timing(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 0.0)  # zero elapsed
        r2 = _make_turn_result(turn=2)
        logger.log_turn_result(2, r2, 4.0)

        config = _make_config()
        report = generate_report(logger, config, "Test", 4.0)
        # Only non-zero turn counted
        assert report.avg_turn_seconds == 4.0
        assert report.fastest_turn_seconds == 4.0

    def test_empty_logger_timing(self):
        logger = PlaytestLogger()
        config = _make_config()
        report = generate_report(logger, config, "Test", 0.0)
        assert report.avg_turn_seconds == 0.0
        assert report.slowest_turn_seconds == 0.0
        assert report.fastest_turn_seconds == 0.0
        assert report.character_response_rate == 0.0

    def test_per_turn_structure(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(
            turn=1,
            characters=[CharacterResponse(character="Maya", response="Hello")],
            beats_hit=["Beat 1"],
        )
        logger.log_turn_result(1, r1, 5.0)

        config = _make_config()
        report = generate_report(logger, config, "Test", 5.0)
        assert len(report.per_turn) == 1
        pt = report.per_turn[0]
        assert pt["turn"] == 1
        assert pt["characters_responded"] == ["Maya"]
        assert pt["beats_hit"] == ["Beat 1"]
        assert pt["elapsed"] == 5.0

    def test_call_log_integration(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)

        call_log = LLMCallLog()
        call_log.log(
            LLMCallRecord(
                timestamp="2026-01-01T00:00:00",
                agent="narrator",
                turn=1,
                prompt_tokens=100,
                thinking_tokens=50,
                content_tokens=200,
                latency_ms=500,
                finish_reason="stop",
                parse_result="success",
                parse_attempts=1,
                retry_count=0,
                temperature=1.0,
                max_tokens=4096,
            )
        )
        call_log.log(
            LLMCallRecord(
                timestamp="2026-01-01T00:00:01",
                agent="memory:maya",
                turn=1,
                prompt_tokens=80,
                thinking_tokens=30,
                content_tokens=100,
                latency_ms=300,
                finish_reason="stop",
                parse_result="yaml_fence_missing",
                parse_attempts=2,
                retry_count=1,
                temperature=0.2,
                max_tokens=2500,
            )
        )

        config = _make_config()
        report = generate_report(logger, config, "Test", 1.0, call_log=call_log)
        assert report.call_log_totals["total_calls"] == 2
        assert report.call_log_summary["narrator"]["total_calls"] == 1
        assert "yaml_fence_missing" in report.parse_failure_breakdown
        assert report.parse_failure_breakdown["yaml_fence_missing"] == 1

    def test_quality_scores_forwarded(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)

        scores = [{"turn": 1, "composite": 0.8}]
        config = _make_config()
        report = generate_report(logger, config, "Test", 1.0, quality_scores=scores)
        assert report.quality_scores == scores

    def test_memory_final_forwarded(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)

        config = _make_config()
        report = generate_report(
            logger,
            config,
            "Test",
            1.0,
            memory_final={"Maya": "summary"},
            memory_final_facts={"Maya": ["fact1"]},
        )
        assert report.memory_final == {"Maya": "summary"}
        assert report.memory_final_facts == {"Maya": ["fact1"]}


# -- generate_report_markdown (extended) ------------------------------------


class TestGenerateReportMarkdownExtended:
    def test_quality_scores_section(self):
        report = PlaytestReport(
            game_id="test",
            game_title="Test",
            timestamp="2026-01-01T00-00-00",
            model="test-model",
            turns_played=1,
            max_turns=5,
            total_duration_seconds=60.0,
            issue_count=0,
            error_count=0,
            issues=[],
            errors=[],
            events=[],
            per_turn=[
                {
                    "turn": 1,
                    "elapsed": 5.0,
                    "characters_responded": [],
                    "beats_hit": [],
                    "issues": [],
                    "is_edge_case": False,
                }
            ],
            memory_final={},
            quality_scores=[
                {
                    "turn": 1,
                    "narration_length_ok": True,
                    "yaml_first_attempt": True,
                    "character_personality": 0.85,
                    "memory_relevance": True,
                    "composite": 0.92,
                }
            ],
            character_response_rate=0.75,
            yaml_parse_success_rate=1.0,
        )
        md = generate_report_markdown(report)
        assert "## Quality Scores" in md
        assert "0.92" in md
        assert "Average composite score:" in md
        assert "Character response rate:" in md
        assert "YAML parse success rate:" in md

    def test_call_log_summary_section(self):
        report = PlaytestReport(
            game_id="test",
            game_title="Test",
            timestamp="2026-01-01T00-00-00",
            model="test-model",
            turns_played=1,
            max_turns=5,
            total_duration_seconds=60.0,
            issue_count=0,
            error_count=0,
            issues=[],
            errors=[],
            events=[],
            per_turn=[],
            memory_final={},
            call_log_totals={
                "total_calls": 5,
                "mean_latency_ms": 400,
                "parse_success_rate": 0.8,
                "total_prompt_tokens": 500,
                "total_thinking_tokens": 200,
                "total_content_tokens": 1000,
                "length_finishes": 1,
                "total_retries": 2,
            },
            call_log_summary={
                "narrator": {
                    "total_calls": 3,
                    "mean_latency_ms": 500,
                    "parse_success_rate": 0.667,
                    "total_retries": 1,
                },
            },
            parse_failure_breakdown={"yaml_fence_missing": 1},
        )
        md = generate_report_markdown(report)
        assert "## LLM Call Summary" in md
        assert "Total calls: 5" in md
        assert "narrator" in md
        assert "### Parse Failures" in md
        assert "yaml_fence_missing: 1" in md

    def test_memory_health_section(self):
        report = PlaytestReport(
            game_id="test",
            game_title="Test",
            timestamp="2026-01-01T00-00-00",
            model="test-model",
            turns_played=1,
            max_turns=5,
            total_duration_seconds=60.0,
            issue_count=0,
            error_count=0,
            issues=[],
            errors=[],
            events=[],
            per_turn=[],
            memory_final={},
            memory_health={
                "per_character": {
                    "Maya": {
                        "avg_fact_count": 3.5,
                        "max_fact_count": 5,
                        "turns_at_cap": 1,
                        "turns_with_overlap": 0,
                        "turns_stale": 2,
                        "total_turns": 4,
                    }
                },
                "turns_with_memory": 4,
            },
        )
        md = generate_report_markdown(report)
        assert "## Memory Health" in md
        assert "Maya" in md
        assert "At Cap" in md
        assert "Stale" in md

    def test_memory_final_with_facts(self):
        report = PlaytestReport(
            game_id="test",
            game_title="Test",
            timestamp="2026-01-01T00-00-00",
            model="test-model",
            turns_played=1,
            max_turns=5,
            total_duration_seconds=60.0,
            issue_count=0,
            error_count=0,
            issues=[],
            errors=[],
            events=[],
            per_turn=[],
            memory_final={"Maya": "Maya remembers everything."},
            memory_final_facts={"Maya": ["fact1", "fact2"]},
        )
        md = generate_report_markdown(report)
        assert "## Memory State (Final)" in md
        assert "Maya remembers everything." in md
        assert "- fact1" in md
        assert "- fact2" in md

    def test_no_errors_section_when_empty(self):
        report = PlaytestReport(
            game_id="test",
            game_title="Test",
            timestamp="2026-01-01T00-00-00",
            model="test-model",
            turns_played=1,
            max_turns=5,
            total_duration_seconds=60.0,
            issue_count=0,
            error_count=0,
            issues=[],
            errors=[],
            events=[],
            per_turn=[],
            memory_final={},
        )
        md = generate_report_markdown(report)
        assert "## Errors" not in md

    def test_per_turn_no_characters(self):
        """Per-turn row shows (none) when no characters responded."""
        report = PlaytestReport(
            game_id="test",
            game_title="Test",
            timestamp="2026-01-01T00-00-00",
            model="test-model",
            turns_played=1,
            max_turns=5,
            total_duration_seconds=60.0,
            issue_count=0,
            error_count=0,
            issues=[],
            errors=[],
            events=[],
            per_turn=[
                {
                    "turn": 1,
                    "elapsed": 3.0,
                    "characters_responded": [],
                    "beats_hit": [],
                    "issues": ["some_issue"],
                    "is_edge_case": False,
                }
            ],
            memory_final={},
        )
        md = generate_report_markdown(report)
        assert "(none)" in md
        assert "some_issue" in md


# -- write_report ----------------------------------------------------------


class TestWriteReportExtended:
    def test_writes_memory_final_yaml(self, tmp_path: Path):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)

        config = _make_config(tmp_path)
        report = generate_report(
            logger,
            config,
            "Test",
            1.0,
            memory_final={"Maya": "She met the player."},
            memory_final_facts={"Maya": ["fact1", "fact2"]},
        )

        output_path = write_report(report, logger, config)
        out_dir = Path(output_path)

        assert (out_dir / "memory_final.yaml").exists()
        with open(out_dir / "memory_final.yaml") as f:
            data = yaml.safe_load(f)
        assert data["Maya"]["summary"] == "She met the player."
        assert data["Maya"]["facts"] == ["fact1", "fact2"]

    def test_no_memory_final_file_when_empty(self, tmp_path: Path):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)

        config = _make_config(tmp_path)
        report = generate_report(logger, config, "Test", 1.0)

        output_path = write_report(report, logger, config)
        out_dir = Path(output_path)

        assert not (out_dir / "memory_final.yaml").exists()

    def test_config_yaml_contents(self, tmp_path: Path):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)

        config = _make_config(tmp_path, player_name="Bob", edge_case_frequency=0.25)
        report = generate_report(logger, config, "Test", 1.0)

        output_path = write_report(report, logger, config)
        out_dir = Path(output_path)

        with open(out_dir / "config.yaml") as f:
            data = yaml.safe_load(f)
        assert data["game_id"] == "test-game"
        assert data["player_name"] == "Bob"
        assert data["edge_case_frequency"] == 0.25

    def test_output_path_stored_on_report(self, tmp_path: Path):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        logger.log_turn_result(1, r1, 1.0)

        config = _make_config(tmp_path)
        report = generate_report(logger, config, "Test", 1.0)
        output_path = write_report(report, logger, config)

        assert report.output_path == output_path
        assert "2026-01-01T00-00-00" in output_path
