"""Tests for PlaytestRunner — covers _detect_issues, _compute_quality_score,
_finalize, and the run() orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from theact.engine.types import (
    CharacterResponse,
    GameStateResult,
    MemoryDiff,
    NarratorOutput,
    TurnResult,
)
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.playtest.config import PlaytestConfig
from theact.playtest.runner import PlaytestRunner


# -- Helpers ---------------------------------------------------------------


def _make_turn_result(
    turn: int = 1,
    narration: str = "You see the beach.",
    characters: list[CharacterResponse] | None = None,
    memory_diffs: list[MemoryDiff] | None = None,
    beats_hit: list[str] | None = None,
    completed: bool = False,
    chapter_advanced: bool = False,
    new_chapter: str | None = None,
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
        chapter_advanced=chapter_advanced,
        new_chapter=new_chapter,
    )


def _make_chapter(**kwargs) -> Chapter:
    defaults = dict(
        id="01-the-crash",
        title="The Crash",
        summary="You wake up on the beach after a plane crash.",
        beats=["Player wakes up", "Player meets Maya"],
        completion="Player has explored the crash site.",
        characters=["maya"],
        next="02-the-discovery",
    )
    defaults.update(kwargs)
    return Chapter(**defaults)


def _make_character(**kwargs) -> Character:
    defaults = dict(
        name="Maya Chen",
        role="A fellow crash survivor.",
        personality="Calm and resourceful. Speaks softly. Protective of others.",
        secret="She was on the plane for a secret reason.",
        relationships={"joaquin": "Trusts him cautiously."},
    )
    defaults.update(kwargs)
    return Character(**defaults)


# -- _detect_issues (extended) ---------------------------------------------


class TestDetectIssuesExtended:
    def test_detects_fact_summary_overlap(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(
            turn=1,
            memory_diffs=[
                MemoryDiff(
                    character="Maya Chen",
                    old_summary="",
                    new_summary="Maya found the ancient golden artifact hidden inside the cave",
                    new_facts=["Maya found the ancient golden artifact hidden inside"],
                )
            ],
        )
        issues = runner._detect_issues(1, result)
        assert any("memory_fact_overlap:maya_chen" in i for i in issues)

    def test_no_overlap_when_facts_differ_from_summary(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(
            turn=1,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="Maya met the player on the beach.",
                    new_facts=["Joaquin disappeared into the jungle at midnight"],
                )
            ],
        )
        issues = runner._detect_issues(1, result)
        assert not any("memory_fact_overlap" in i for i in issues)

    def test_no_overlap_when_no_summary(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(
            turn=1,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="",
                    new_facts=["Some fact about Maya"],
                )
            ],
        )
        issues = runner._detect_issues(1, result)
        assert not any("memory_fact_overlap" in i for i in issues)

    def test_no_overlap_when_no_facts(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(
            turn=1,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="Maya met the player.",
                    new_facts=[],
                )
            ],
        )
        issues = runner._detect_issues(1, result)
        assert not any("memory_fact_overlap" in i for i in issues)

    def test_detects_stale_facts(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        same_facts = ["fact1", "fact2"]

        # Log turn 1 to establish prior state
        r1 = _make_turn_result(
            turn=1,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="summary",
                    new_facts=same_facts,
                )
            ],
        )
        runner.logger.log_turn_result(1, r1, 1.0)

        # Turn 2 with identical facts
        r2 = _make_turn_result(
            turn=2,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="summary",
                    new_facts=same_facts,
                )
            ],
        )
        issues = runner._detect_issues(2, r2)
        assert any("memory_stale:maya" in i for i in issues)

    def test_no_stale_when_facts_change(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))

        r1 = _make_turn_result(
            turn=1,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="summary",
                    new_facts=["fact1"],
                )
            ],
        )
        runner.logger.log_turn_result(1, r1, 1.0)

        r2 = _make_turn_result(
            turn=2,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="summary",
                    new_facts=["fact1", "fact2"],  # changed
                )
            ],
        )
        issues = runner._detect_issues(2, r2)
        assert not any("memory_stale" in i for i in issues)

    def test_no_stale_on_first_turn(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        r1 = _make_turn_result(
            turn=1,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="summary",
                    new_facts=["fact1"],
                )
            ],
        )
        issues = runner._detect_issues(1, r1)
        assert not any("memory_stale" in i for i in issues)

    def test_multiple_issues_in_one_turn(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(
            turn=1,
            narration="",  # empty narrator
            characters=[
                CharacterResponse(character="Maya", response=""),  # empty char
            ],
        )
        issues = runner._detect_issues(1, result)
        assert "empty_narrator_response" in issues
        assert "empty_character_response:Maya" in issues


# -- _compute_quality_score ------------------------------------------------


class TestComputeQualityScore:
    def test_basic_quality_score(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))

        char = _make_character()
        game = MagicMock()
        game.__class__.__name__ = "LoadedGame"
        # Make isinstance check pass
        from theact.models.game import LoadedGame

        game.__class__ = LoadedGame
        game.characters = {"maya": char}

        result = _make_turn_result(
            turn=1,
            narration=" ".join(["word"] * 200),  # in the 150-300 range
            characters=[
                CharacterResponse(
                    character="Maya Chen", response="I am calm and resourceful."
                )
            ],
            memory_diffs=[
                MemoryDiff(
                    character="Maya Chen",
                    old_summary="",
                    new_summary="summary",
                    new_facts=["Player arrived on the beach"],
                )
            ],
        )

        # Log the turn first so logger has it
        runner.logger.log_turn_result(1, result, 1.0)
        runner._compute_quality_score(1, result, game)

        assert len(runner._quality_scores) == 1
        score = runner._quality_scores[0]
        assert score["turn"] == 1
        assert "composite" in score
        assert score["narration_length_ok"] is True

    def test_skips_for_non_loaded_game(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(turn=1)
        runner._compute_quality_score(1, result, "not_a_game")
        assert len(runner._quality_scores) == 0

    def test_short_narration_flagged(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))

        from theact.models.game import LoadedGame

        game = MagicMock()
        game.__class__ = LoadedGame
        game.characters = {}

        result = _make_turn_result(turn=1, narration="Short text.")
        runner.logger.log_turn_result(1, result, 1.0)
        runner._compute_quality_score(1, result, game)

        assert len(runner._quality_scores) == 1
        assert runner._quality_scores[0]["narration_length_ok"] is False


# -- _finalize -------------------------------------------------------------


class TestFinalize:
    def test_finalize_produces_report(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="test",
            max_turns=5,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )
        runner = PlaytestRunner(config)
        runner._game_title = "Test Game"

        # Add some turns
        r1 = _make_turn_result(turn=1)
        runner.logger.log_turn_result(1, r1, 2.0)

        import time

        start = time.monotonic()
        report = runner._finalize(start)

        assert report.game_id == "test"
        assert report.turns_played == 1
        assert report.game_title == "Test Game"

        # Check files were written
        out_dir = tmp_path / "reports" / "2026-01-01T00-00-00"
        assert (out_dir / "report.md").exists()
        assert (out_dir / "config.yaml").exists()
        assert (out_dir / "llm_calls.yaml").exists()

    def test_finalize_collects_memory_from_last_turn(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="test",
            max_turns=5,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )
        runner = PlaytestRunner(config)
        runner._game_title = "Test Game"

        r1 = _make_turn_result(
            turn=1,
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="Maya met the player.",
                    new_facts=["fact1"],
                )
            ],
        )
        runner.logger.log_turn_result(1, r1, 1.0)

        import time

        report = runner._finalize(time.monotonic())
        assert report.memory_final == {"Maya": "Maya met the player."}
        assert report.memory_final_facts == {"Maya": ["fact1"]}

    def test_finalize_with_no_turns(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="test",
            max_turns=5,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )
        runner = PlaytestRunner(config)
        runner._game_title = "Test"

        import time

        report = runner._finalize(time.monotonic())
        assert report.turns_played == 0
        assert report.memory_final == {}

    def test_finalize_uses_game_id_when_title_missing(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="my-game",
            max_turns=5,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )
        runner = PlaytestRunner(config)
        # Don't set _game_title

        import time

        report = runner._finalize(time.monotonic())
        assert report.game_title == "my-game"


# -- run() orchestrator (mocked) -------------------------------------------


class TestRunOrchestrator:
    @pytest.mark.asyncio
    async def test_basic_run(self, tmp_path: Path):
        """Test that run() executes opening + turns and returns a report."""
        config = PlaytestConfig(
            game_id="test",
            max_turns=2,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
            opening_action="I look around.",
        )
        runner = PlaytestRunner(config)

        opening_result = _make_turn_result(turn=0, narration="Opening narration.")
        turn1_result = _make_turn_result(
            turn=1,
            narration="You look around the beach.",
            characters=[CharacterResponse(character="Maya", response="Welcome.")],
        )
        turn2_result = _make_turn_result(turn=2, narration="You explore further.")

        mock_game = MagicMock()
        mock_game.meta.title = "Test Game"
        mock_game.state.current_chapter = "01-the-crash"
        mock_game.state.game_complete = False
        mock_game.chapters = {"01-the-crash": _make_chapter()}
        mock_game.characters = {}

        call_count = 0

        async def mock_run_turn(game, player_input, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return opening_result
            elif call_count == 2:
                return turn1_result
            else:
                return turn2_result

        async def mock_decide(conversation_tail, chapter, turn_number):
            return "I walk forward."

        with (
            patch("theact.playtest.runner.create_save"),
            patch("theact.playtest.runner.load_save", return_value=mock_game),
            patch("theact.playtest.runner.run_turn", side_effect=mock_run_turn),
            patch.object(runner.player_agent, "decide", side_effect=mock_decide),
        ):
            report = await runner.run()

        assert report.turns_played >= 2
        assert report.game_title == "Test Game"

    @pytest.mark.asyncio
    async def test_run_stops_on_error(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="test",
            max_turns=5,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
            stop_on_error=True,
        )
        runner = PlaytestRunner(config)

        mock_game = MagicMock()
        mock_game.meta.title = "Test"
        mock_game.state.current_chapter = "01-the-crash"
        mock_game.state.game_complete = False
        mock_game.chapters = {"01-the-crash": _make_chapter()}
        mock_game.characters = {}

        async def mock_run_turn(game, player_input, **kwargs):
            raise RuntimeError("LLM timeout")

        with (
            patch("theact.playtest.runner.create_save"),
            patch("theact.playtest.runner.load_save", return_value=mock_game),
            patch("theact.playtest.runner.run_turn", side_effect=mock_run_turn),
        ):
            report = await runner.run()

        # Should stop early due to opening narration failure with stop_on_error
        assert report.error_count >= 1

    @pytest.mark.asyncio
    async def test_run_continues_on_error(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="test",
            max_turns=2,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
            stop_on_error=False,
        )
        runner = PlaytestRunner(config)

        mock_game = MagicMock()
        mock_game.meta.title = "Test"
        mock_game.state.current_chapter = "01-the-crash"
        mock_game.state.game_complete = False
        mock_game.chapters = {"01-the-crash": _make_chapter()}
        mock_game.characters = {}

        call_count = 0

        async def mock_run_turn(game, player_input, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Opening succeeds
                return _make_turn_result(turn=0, narration="Opening.")
            elif call_count == 2:
                raise RuntimeError("error on turn 1")
            else:
                return _make_turn_result(turn=2, narration="Recovered.")

        async def mock_decide(conversation_tail, chapter, turn_number):
            return "I proceed."

        with (
            patch("theact.playtest.runner.create_save"),
            patch("theact.playtest.runner.load_save", return_value=mock_game),
            patch("theact.playtest.runner.run_turn", side_effect=mock_run_turn),
            patch.object(runner.player_agent, "decide", side_effect=mock_decide),
        ):
            report = await runner.run()

        assert report.error_count >= 1
        # Should have continued past the error

    @pytest.mark.asyncio
    async def test_run_stops_on_game_complete(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="test",
            max_turns=10,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )
        runner = PlaytestRunner(config)

        mock_game = MagicMock()
        mock_game.meta.title = "Test"
        mock_game.state.current_chapter = "01-the-crash"
        mock_game.state.game_complete = False
        mock_game.chapters = {"01-the-crash": _make_chapter()}
        mock_game.characters = {}

        call_count = 0

        async def mock_run_turn(game, player_input, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_turn_result(turn=0, narration="Opening.")
            elif call_count == 2:
                # This turn completes the game
                mock_game.state.game_complete = True
                return _make_turn_result(
                    turn=1,
                    narration="The end.",
                    chapter_advanced=True,
                    new_chapter=None,
                )
            else:
                return _make_turn_result(turn=call_count, narration="More.")

        async def mock_decide(conversation_tail, chapter, turn_number):
            return "I continue."

        with (
            patch("theact.playtest.runner.create_save"),
            patch("theact.playtest.runner.load_save", return_value=mock_game),
            patch("theact.playtest.runner.run_turn", side_effect=mock_run_turn),
            patch.object(runner.player_agent, "decide", side_effect=mock_decide),
        ):
            await runner.run()

        # Should have logged a game_over event and stopped
        assert any("game_over" in str(e) for e in runner.logger.events)

    @pytest.mark.asyncio
    async def test_run_with_on_turn_complete_callback(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="test",
            max_turns=1,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )
        runner = PlaytestRunner(config)

        mock_game = MagicMock()
        mock_game.meta.title = "Test"
        mock_game.state.current_chapter = "01-the-crash"
        mock_game.state.game_complete = False
        mock_game.chapters = {"01-the-crash": _make_chapter()}
        mock_game.characters = {}

        call_count = 0

        async def mock_run_turn(game, player_input, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_turn_result(turn=0, narration="Opening.")
            return _make_turn_result(turn=1, narration="Beach scene.")

        callback_calls = []

        def on_turn_complete(turn_num, turn_log, quality_score):
            callback_calls.append((turn_num, turn_log, quality_score))

        with (
            patch("theact.playtest.runner.create_save"),
            patch("theact.playtest.runner.load_save", return_value=mock_game),
            patch("theact.playtest.runner.run_turn", side_effect=mock_run_turn),
        ):
            await runner.run(on_turn_complete=on_turn_complete)

        assert len(callback_calls) >= 1

    @pytest.mark.asyncio
    async def test_run_stops_when_chapter_not_found(self, tmp_path: Path):
        config = PlaytestConfig(
            game_id="test",
            max_turns=5,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )
        runner = PlaytestRunner(config)

        mock_game = MagicMock()
        mock_game.meta.title = "Test"
        mock_game.state.current_chapter = "nonexistent-chapter"
        mock_game.state.game_complete = False
        mock_game.chapters = {"01-the-crash": _make_chapter()}
        mock_game.characters = {}

        call_count = 0

        async def mock_run_turn(game, player_input, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_turn_result(turn=0, narration="Opening.")

        with (
            patch("theact.playtest.runner.create_save"),
            patch("theact.playtest.runner.load_save", return_value=mock_game),
            patch("theact.playtest.runner.run_turn", side_effect=mock_run_turn),
        ):
            report = await runner.run()

        # Opening + turn 1 (uses opening_action), then turn 2 would need
        # chapter lookup which fails => stops
        # The key is it doesn't crash and produces a valid report
        assert report is not None
