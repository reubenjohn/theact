"""Tests for the playtest framework."""

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
from theact.playtest.config import PlaytestConfig
from theact.playtest.logger import PlaytestLogger, TurnLog
from theact.playtest.player_agent import (
    DIRECT_INJECTION_ALL,
    DIRECT_INJECTION_CONTRADICTORY,
    DIRECT_INJECTION_FOURTH_WALL,
    DIRECT_INJECTION_NONSENSE,
    DIRECT_INJECTION_SHORT,
    EDGE_CASE_PROMPTS,
    PLAYER_SYSTEM_PROMPT,
    PlayerDecision,
)
from theact.playtest.report import (
    PlaytestReport,
    generate_report,
    generate_report_markdown,
    write_report,
)
from theact.playtest.runner import PlaytestRunner


# -- Helpers ---------------------------------------------------------------


def _make_turn_result(
    turn: int = 1,
    narration: str = "You see the beach.",
    characters: list[CharacterResponse] | None = None,
    memory_diffs: list[MemoryDiff] | None = None,
    beats_hit: list[str] | None = None,
    completed: bool = False,
) -> TurnResult:
    """Build a synthetic TurnResult for testing."""
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


# -- PlaytestConfig --------------------------------------------------------


class TestPlaytestConfig:
    def test_defaults(self):
        config = PlaytestConfig(game_id="test")
        assert config.game_id == "test"
        assert config.max_turns == 20
        assert config.player_name == "Alex"
        assert config.edge_case_frequency == 0.15
        assert config.direct_edge_case_frequency == 0.05
        assert config.nonsense_frequency == 0.03
        assert config.repeat_frequency == 0.03
        assert config.timestamp != ""  # auto-filled

    def test_debug_defaults_false(self):
        config = PlaytestConfig(game_id="test")
        assert config.debug is False

    def test_debug_can_be_enabled(self):
        config = PlaytestConfig(game_id="test", debug=True)
        assert config.debug is True

    def test_custom_timestamp_preserved(self):
        config = PlaytestConfig(game_id="test", timestamp="2026-01-01T00-00-00")
        assert config.timestamp == "2026-01-01T00-00-00"

    def test_auto_timestamp_format(self):
        config = PlaytestConfig(game_id="test")
        # Should match YYYY-MM-DDTHH-MM-SS pattern
        parts = config.timestamp.split("T")
        assert len(parts) == 2
        assert len(parts[0].split("-")) == 3
        assert len(parts[1].split("-")) == 3


# -- TurnLog ---------------------------------------------------------------


class TestTurnLog:
    def test_creation(self):
        log = TurnLog(turn=1, player_input="I look around.")
        assert log.turn == 1
        assert log.player_input == "I look around."
        assert log.narrator_text == ""
        assert log.character_texts == {}
        assert log.issues == []

    def test_fields_populated(self):
        log = TurnLog(
            turn=3,
            player_input="I walk to the beach.",
            narrator_text="You walk to the beach.",
            character_texts={"Maya Chen": "Be careful."},
            characters_responded=["Maya Chen"],
            beats_hit=["Player explores the beach"],
            elapsed_seconds=12.5,
        )
        assert log.characters_responded == ["Maya Chen"]
        assert log.elapsed_seconds == 12.5


# -- PlaytestLogger -------------------------------------------------------


class TestPlaytestLogger:
    def test_log_turn_result(self):
        logger = PlaytestLogger()
        result = _make_turn_result(
            turn=1,
            narration="You wake up on the sand.",
            characters=[
                CharacterResponse(character="Maya Chen", response="Hey, are you okay?")
            ],
        )
        logger.log_player_input(1, "I look around.")
        logger.log_turn_result(1, result, 5.0)

        assert len(logger.turns) == 1
        assert logger.turns[0].player_input == "I look around."
        assert logger.turns[0].narrator_text == "You wake up on the sand."
        assert logger.turns[0].character_texts["Maya Chen"] == "Hey, are you okay?"
        assert logger.turns[0].elapsed_seconds == 5.0

    def test_log_error(self):
        logger = PlaytestLogger()
        logger.log_error(3, RuntimeError("LLM timeout"))
        assert len(logger.errors) == 1
        assert logger.errors[0][0] == 3
        assert "RuntimeError" in logger.errors[0][1]

    def test_log_issue(self):
        logger = PlaytestLogger()
        result = _make_turn_result(turn=1)
        logger.log_turn_result(1, result, 1.0)
        logger.log_issue(1, "empty_narrator_response")
        assert logger.turns[0].issues == ["empty_narrator_response"]

    def test_log_event(self):
        logger = PlaytestLogger()
        logger.log_event(5, "chapter_completed", "02-the-discovery")
        assert len(logger.events) == 1
        assert logger.events[0] == (5, "chapter_completed", "02-the-discovery")

    def test_all_issues(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1)
        r2 = _make_turn_result(turn=2)
        logger.log_turn_result(1, r1, 1.0)
        logger.log_turn_result(2, r2, 1.0)
        logger.log_issue(1, "issue_a")
        logger.log_issue(2, "issue_b")
        logger.log_issue(2, "issue_c")
        issues = logger.all_issues()
        assert len(issues) == 3
        assert issues[0] == (1, "issue_a")
        assert issues[1] == (2, "issue_b")


class TestIsRepeating:
    def test_not_repeating_with_empty_history(self):
        logger = PlaytestLogger()
        assert not logger.is_repeating("You walk to the beach.")

    def test_not_repeating_with_different_text(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1, narration="The jungle looms ahead.")
        logger.log_turn_result(1, r1, 1.0)
        assert not logger.is_repeating("A bright fire crackles in the camp.")

    def test_detects_exact_repetition(self):
        logger = PlaytestLogger()
        text = "You see the waves crashing on the shore ahead of you."
        r1 = _make_turn_result(turn=1, narration=text)
        logger.log_turn_result(1, r1, 1.0)
        assert logger.is_repeating(text)

    def test_detects_near_repetition(self):
        logger = PlaytestLogger()
        text1 = "You see the bright waves crashing on the shore ahead."
        text2 = "You see the large waves crashing on the shore ahead."
        r1 = _make_turn_result(turn=1, narration=text1)
        logger.log_turn_result(1, r1, 1.0)
        assert logger.is_repeating(text2)

    def test_window_limits_check(self):
        logger = PlaytestLogger()
        target = "This is the target text with specific words inside."
        # Add a matching turn, then 3 different ones to push it outside the window
        r = _make_turn_result(turn=1, narration=target)
        logger.log_turn_result(1, r, 1.0)
        for i in range(2, 5):
            r = _make_turn_result(
                turn=i, narration=f"Completely different text number {i} here."
            )
            logger.log_turn_result(i, r, 1.0)
        # With window=3, only turns 2-4 are checked, so target should not match
        assert not logger.is_repeating(target, window=3)

    def test_handles_empty_text(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1, narration="")
        logger.log_turn_result(1, r1, 1.0)
        # Empty text should not flag as repeating (both empty sets)
        assert not logger.is_repeating("Some actual content here.")

    def test_empty_input_no_crash(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1, narration="Some text here.")
        logger.log_turn_result(1, r1, 1.0)
        # Empty input should not crash or flag (empty set)
        assert not logger.is_repeating("")


class TestRecentConversation:
    def test_returns_empty_with_no_turns(self):
        logger = PlaytestLogger()
        assert logger.recent_conversation(n=6) == []

    def test_returns_correct_entries(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(
            turn=1,
            narration="You wake up.",
            characters=[CharacterResponse(character="Maya Chen", response="Hi there.")],
        )
        logger.log_player_input(1, "I stand up.")
        logger.log_turn_result(1, r1, 1.0)

        entries = logger.recent_conversation(n=10)
        assert len(entries) == 3  # narrator + player + character
        assert entries[0].role == "narrator"
        assert entries[1].role == "player"
        assert entries[2].role == "character"
        assert entries[2].character == "Maya Chen"

    def test_respects_limit(self):
        logger = PlaytestLogger()
        for i in range(1, 6):
            r = _make_turn_result(turn=i, narration=f"Narration {i}.")
            logger.log_player_input(i, f"Action {i}.")
            logger.log_turn_result(i, r, 1.0)

        entries = logger.recent_conversation(n=3)
        assert len(entries) == 3


class TestFlushToDisk:
    def test_creates_output_files(self, tmp_path: Path):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1, narration="You wake up.")
        logger.log_player_input(1, "I look around.")
        logger.log_turn_result(1, r1, 2.5)

        logger.flush_to_disk(str(tmp_path), "test-timestamp")

        out_dir = tmp_path / "test-timestamp"
        assert out_dir.exists()
        assert (out_dir / "conversation.yaml").exists()
        assert (out_dir / "timing.yaml").exists()

        # Verify conversation data
        with open(out_dir / "conversation.yaml") as f:
            data = yaml.safe_load(f)
        assert len(data) == 1
        assert data[0]["turn"] == 1
        assert data[0]["player_input"] == "I look around."

    def test_writes_errors(self, tmp_path: Path):
        logger = PlaytestLogger()
        logger.log_error(2, RuntimeError("test error"))

        logger.flush_to_disk(str(tmp_path), "err-test")

        out_dir = tmp_path / "err-test"
        assert (out_dir / "errors.yaml").exists()

        with open(out_dir / "errors.yaml") as f:
            data = yaml.safe_load(f)
        assert len(data) == 1
        assert data[0]["turn"] == 2

    def test_incremental_updates(self, tmp_path: Path):
        logger = PlaytestLogger()

        # First flush
        r1 = _make_turn_result(turn=1, narration="Turn 1.")
        logger.log_turn_result(1, r1, 1.0)
        logger.flush_to_disk(str(tmp_path), "incr")

        # Second flush with more data
        r2 = _make_turn_result(turn=2, narration="Turn 2.")
        logger.log_turn_result(2, r2, 1.0)
        logger.flush_to_disk(str(tmp_path), "incr")

        with open(tmp_path / "incr" / "conversation.yaml") as f:
            data = yaml.safe_load(f)
        assert len(data) == 2


# -- PlaytestReport -------------------------------------------------------


class TestReport:
    def _make_report(self) -> PlaytestReport:
        return PlaytestReport(
            game_id="lost-island",
            game_title="The Lost Island",
            timestamp="2026-03-20T14-30-00",
            model="test-model",
            turns_played=5,
            max_turns=10,
            total_duration_seconds=120.5,
            issue_count=2,
            error_count=1,
            issues=[(2, "empty_narrator_response"), (4, "narrator_repeating")],
            errors=[(3, "RuntimeError: timeout")],
            events=[(5, "chapter_completed", "02-the-discovery")],
            per_turn=[
                {
                    "turn": 1,
                    "elapsed": 12.3,
                    "characters_responded": ["Maya Chen"],
                    "beats_hit": [],
                    "issues": [],
                    "is_edge_case": False,
                },
                {
                    "turn": 2,
                    "elapsed": 8.1,
                    "characters_responded": [],
                    "beats_hit": ["Player wakes on the beach"],
                    "issues": ["empty_narrator_response"],
                    "is_edge_case": False,
                },
            ],
            memory_final={"Maya Chen": "Met the player on the beach."},
            avg_turn_seconds=10.2,
            slowest_turn_seconds=12.3,
            fastest_turn_seconds=8.1,
        )

    def test_report_creation(self):
        report = self._make_report()
        assert report.turns_played == 5
        assert report.issue_count == 2
        assert report.error_count == 1

    def test_markdown_contains_header(self):
        report = self._make_report()
        md = generate_report_markdown(report)
        assert "# Playtest Report" in md
        assert "**Game:** The Lost Island" in md
        assert "**Turns:** 5 / 10" in md
        assert "**Model:** test-model" in md

    def test_markdown_contains_issues(self):
        report = self._make_report()
        md = generate_report_markdown(report)
        assert "empty_narrator_response" in md
        assert "narrator_repeating" in md

    def test_markdown_contains_errors(self):
        report = self._make_report()
        md = generate_report_markdown(report)
        assert "RuntimeError: timeout" in md

    def test_markdown_contains_timing(self):
        report = self._make_report()
        md = generate_report_markdown(report)
        assert "Average turn: 10.2s" in md
        assert "Slowest turn: 12.3s" in md

    def test_markdown_contains_per_turn(self):
        report = self._make_report()
        md = generate_report_markdown(report)
        assert "Maya Chen" in md
        assert "Per-Turn Detail" in md

    def test_markdown_contains_events(self):
        report = self._make_report()
        md = generate_report_markdown(report)
        assert "chapter_completed" in md

    def test_markdown_contains_memory(self):
        report = self._make_report()
        md = generate_report_markdown(report)
        assert "Memory State (Final)" in md
        assert "Met the player on the beach." in md

    def test_markdown_no_issues_message(self):
        report = self._make_report()
        report.issues = []
        report.issue_count = 0
        md = generate_report_markdown(report)
        assert "No issues detected." in md

    def test_markdown_duration_format(self):
        report = self._make_report()
        md = generate_report_markdown(report)
        assert "2m 0s" in md


class TestGenerateReport:
    def test_generates_from_logger(self):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1, narration="You wake up.")
        logger.log_player_input(1, "I look around.")
        logger.log_turn_result(1, r1, 5.0)

        r2 = _make_turn_result(turn=2, narration="The beach stretches ahead.")
        logger.log_player_input(2, "I walk forward.")
        logger.log_turn_result(2, r2, 3.0)

        config = PlaytestConfig(
            game_id="test-game",
            max_turns=10,
            timestamp="2026-01-01T00-00-00",
        )

        report = generate_report(
            logger=logger,
            config=config,
            game_title="Test Game",
            total_duration=8.0,
        )

        assert report.turns_played == 2
        assert report.avg_turn_seconds == 4.0
        assert report.slowest_turn_seconds == 5.0
        assert report.fastest_turn_seconds == 3.0
        assert report.error_count == 0
        assert report.issue_count == 0


class TestWriteReport:
    def test_creates_output_directory(self, tmp_path: Path):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1, narration="Test.")
        logger.log_turn_result(1, r1, 1.0)

        config = PlaytestConfig(
            game_id="test-game",
            max_turns=5,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )

        report = generate_report(
            logger=logger,
            config=config,
            game_title="Test Game",
            total_duration=1.0,
        )

        output_path = write_report(report, logger, config)

        out_dir = Path(output_path)
        assert out_dir.exists()
        assert (out_dir / "report.md").exists()
        assert (out_dir / "config.yaml").exists()
        assert (out_dir / "conversation.yaml").exists()
        assert (out_dir / "timing.yaml").exists()

    def test_report_md_content(self, tmp_path: Path):
        logger = PlaytestLogger()
        r1 = _make_turn_result(turn=1, narration="Test content.")
        logger.log_turn_result(1, r1, 1.0)

        config = PlaytestConfig(
            game_id="test-game",
            max_turns=5,
            timestamp="2026-01-01T00-00-00",
            output_dir=str(tmp_path / "reports"),
        )

        report = generate_report(
            logger=logger,
            config=config,
            game_title="Test Game",
            total_duration=1.0,
        )

        output_path = write_report(report, logger, config)
        md_content = (Path(output_path) / "report.md").read_text()
        assert "# Playtest Report" in md_content
        assert "Test Game" in md_content


# -- Player Agent (prompt construction, no LLM call) ----------------------


class TestPlayerAgentPrompt:
    def test_system_prompt_exists(self):
        assert "crash survivor" in PLAYER_SYSTEM_PROMPT
        assert "1-2 sentences" in PLAYER_SYSTEM_PROMPT

    def test_edge_case_prompts_list(self):
        assert len(EDGE_CASE_PROMPTS) == 10
        for p in EDGE_CASE_PROMPTS:
            assert isinstance(p, str)
            assert len(p) > 10


# -- Issue Detection -------------------------------------------------------


class TestIssueDetection:
    def test_detects_empty_narrator(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(turn=1, narration="")
        # Detect before logging (matches runner flow)
        detected = runner._detect_issues(1, result)
        runner.logger.log_turn_result(1, result, 1.0)
        for issue in detected:
            runner.logger.log_issue(1, issue)
        issues = runner.logger.all_issues()
        assert any("empty_narrator_response" in i for _, i in issues)

    def test_detects_empty_character_response(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(
            turn=1,
            narration="You see the beach.",
            characters=[CharacterResponse(character="Maya Chen", response="")],
        )
        detected = runner._detect_issues(1, result)
        runner.logger.log_turn_result(1, result, 1.0)
        for issue in detected:
            runner.logger.log_issue(1, issue)
        issues = runner.logger.all_issues()
        assert any("empty_character_response:Maya Chen" in i for _, i in issues)

    def test_detects_narrator_repeating(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        text = "The waves crash against the rocks on the distant shore ahead."
        r1 = _make_turn_result(turn=1, narration=text)
        runner.logger.log_turn_result(1, r1, 1.0)

        r2 = _make_turn_result(turn=2, narration=text)
        # Detect before logging turn 2 -- compares against turn 1
        detected = runner._detect_issues(2, r2)
        runner.logger.log_turn_result(2, r2, 1.0)
        for issue in detected:
            runner.logger.log_issue(2, issue)
        issues = runner.logger.all_issues()
        assert any("narrator_repeating" in i for _, i in issues)

    def test_detects_memory_at_cap(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(
            turn=1,
            narration="Some text.",
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="New summary",
                    new_facts=[f"Fact {i}" for i in range(7)],
                )
            ],
        )
        detected = runner._detect_issues(1, result)
        runner.logger.log_turn_result(1, result, 1.0)
        for issue in detected:
            runner.logger.log_issue(1, issue)
        issues = runner.logger.all_issues()
        assert any("memory_at_cap:Maya" in i for _, i in issues)

    def test_no_false_positives_for_different_narration(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        r1 = _make_turn_result(turn=1, narration="The jungle is dark and humid.")
        runner.logger.log_turn_result(1, r1, 1.0)

        r2 = _make_turn_result(
            turn=2, narration="Bright sunlight bathes the camp in warmth."
        )
        # Detect before logging -- compares against turn 1 only
        detected = runner._detect_issues(2, r2)
        runner.logger.log_turn_result(2, r2, 1.0)
        for issue in detected:
            runner.logger.log_issue(2, issue)
        issues = runner.logger.all_issues()
        assert not any("narrator_repeating" in i for _, i in issues)

    def test_no_memory_at_cap_under_limit(self):
        runner = PlaytestRunner(PlaytestConfig(game_id="test"))
        result = _make_turn_result(
            turn=1,
            narration="Some text.",
            memory_diffs=[
                MemoryDiff(
                    character="Maya",
                    old_summary="",
                    new_summary="New summary",
                    new_facts=[f"Fact {i}" for i in range(5)],
                )
            ],
        )
        detected = runner._detect_issues(1, result)
        runner.logger.log_turn_result(1, result, 1.0)
        for issue in detected:
            runner.logger.log_issue(1, issue)
        issues = runner.logger.all_issues()
        assert not any("memory_at_cap" in i for _, i in issues)


# -- Game File Verification ------------------------------------------------


class TestLostIslandGameFiles:
    """Verify the Lost Island game files load correctly through the model layer."""

    def test_load_game_meta(self, games_dir: Path):
        from theact.io.yaml_io import load_yaml
        from theact.models.game import GameMeta

        meta = load_yaml(games_dir / "lost-island" / "game.yaml", GameMeta)
        assert meta.id == "lost-island"
        assert meta.title == "The Lost Island"
        assert meta.characters == ["maya", "joaquin"]
        assert meta.chapters == ["01-the-crash", "02-the-discovery", "03-the-heart"]

    def test_load_world(self, games_dir: Path):
        from theact.io.yaml_io import load_yaml
        from theact.models.world import World

        world = load_yaml(games_dir / "lost-island" / "world.yaml", World)
        assert "South Pacific" in world.setting
        assert "Second person" in world.tone
        assert (
            "supernatural" in world.rules.lower() or "ambiguous" in world.rules.lower()
        )

    def test_load_maya(self, games_dir: Path):
        from theact.io.yaml_io import load_yaml
        from theact.models.character import Character

        maya = load_yaml(
            games_dir / "lost-island" / "characters" / "maya.yaml", Character
        )
        assert maya.name == "Maya Chen"
        assert "joaquin" in maya.relationships

    def test_load_joaquin(self, games_dir: Path):
        from theact.io.yaml_io import load_yaml
        from theact.models.character import Character

        joaquin = load_yaml(
            games_dir / "lost-island" / "characters" / "joaquin.yaml", Character
        )
        assert joaquin.name == "Father Joaquin Reyes"
        assert "maya" in joaquin.relationships

    def test_load_chapter_01(self, games_dir: Path):
        from theact.io.yaml_io import load_yaml
        from theact.models.chapter import Chapter

        ch = load_yaml(
            games_dir / "lost-island" / "chapters" / "01-the-crash.yaml", Chapter
        )
        assert ch.id == "01-the-crash"
        assert ch.next == "02-the-discovery"
        assert len(ch.beats) == 6
        assert "maya" in ch.characters
        assert "joaquin" in ch.characters

    def test_load_chapter_02(self, games_dir: Path):
        from theact.io.yaml_io import load_yaml
        from theact.models.chapter import Chapter

        ch = load_yaml(
            games_dir / "lost-island" / "chapters" / "02-the-discovery.yaml",
            Chapter,
        )
        assert ch.id == "02-the-discovery"
        assert ch.next == "03-the-heart"
        assert len(ch.beats) == 6

    def test_load_chapter_03(self, games_dir: Path):
        from theact.io.yaml_io import load_yaml
        from theact.models.chapter import Chapter

        ch = load_yaml(
            games_dir / "lost-island" / "chapters" / "03-the-heart.yaml",
            Chapter,
        )
        assert ch.id == "03-the-heart"
        assert ch.next is None
        assert len(ch.beats) == 6

    def test_chapter_chain(self, games_dir: Path):
        """Verify chapters form a valid chain: 01 -> 02 -> 03 -> null."""
        from theact.io.yaml_io import load_yaml
        from theact.models.chapter import Chapter

        ch1 = load_yaml(
            games_dir / "lost-island" / "chapters" / "01-the-crash.yaml", Chapter
        )
        ch2 = load_yaml(
            games_dir / "lost-island" / "chapters" / "02-the-discovery.yaml",
            Chapter,
        )
        ch3 = load_yaml(
            games_dir / "lost-island" / "chapters" / "03-the-heart.yaml",
            Chapter,
        )
        assert ch1.next == ch2.id
        assert ch2.next == ch3.id
        assert ch3.next is None

    def test_create_and_load_save(self, games_dir: Path, saves_dir: Path):
        """Verify a save can be created and loaded from the game definition."""
        from theact.io.save_manager import create_save, load_save

        create_save(
            "lost-island",
            "playtest-verify",
            "Alex",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        game = load_save("playtest-verify", saves_dir=saves_dir)

        assert game.meta.id == "lost-island"
        assert "maya" in game.characters
        assert "joaquin" in game.characters
        assert "01-the-crash" in game.chapters
        assert "02-the-discovery" in game.chapters
        assert "03-the-heart" in game.chapters
        assert game.state.player_name == "Alex"
        assert game.state.current_chapter == "01-the-crash"
        assert game.state.turn == 0

    def test_game_file_sizes(self, games_dir: Path):
        """Verify game files stay within size budgets."""
        game_dir = games_dir / "lost-island"

        world_size = (game_dir / "world.yaml").stat().st_size
        assert world_size < 500, f"world.yaml is {world_size} bytes (budget: 500)"

        for name in ["maya.yaml", "joaquin.yaml"]:
            char_size = (game_dir / "characters" / name).stat().st_size
            assert char_size < 400, f"{name} is {char_size} bytes (budget: 400)"

        for name in [
            "01-the-crash.yaml",
            "02-the-discovery.yaml",
            "03-the-heart.yaml",
        ]:
            chap_size = (game_dir / "chapters" / name).stat().st_size
            assert chap_size < 800, f"{name} is {chap_size} bytes (budget: 800)"


# -- Enhanced Edge Case Injection -------------------------------------------


class TestPlayerDecision:
    def test_default_type(self):
        d = PlayerDecision(action="I look around.")
        assert d.action == "I look around."
        assert d.edge_case_type == "normal"

    def test_custom_type(self):
        d = PlayerDecision(action="ok", edge_case_type="direct_injection")
        assert d.edge_case_type == "direct_injection"


class TestDirectInjectionConstants:
    def test_short_inputs(self):
        assert "ok" in DIRECT_INJECTION_SHORT
        assert "sure" in DIRECT_INJECTION_SHORT
        assert "yes" in DIRECT_INJECTION_SHORT
        assert "no" in DIRECT_INJECTION_SHORT
        assert "." in DIRECT_INJECTION_SHORT
        assert "I wait." in DIRECT_INJECTION_SHORT

    def test_nonsense_inputs(self):
        assert "asdf jkl;" in DIRECT_INJECTION_NONSENSE
        assert "sudo rm -rf /" in DIRECT_INJECTION_NONSENSE
        assert len(DIRECT_INJECTION_NONSENSE) >= 3

    def test_fourth_wall_inputs(self):
        assert "I know this is a game" in DIRECT_INJECTION_FOURTH_WALL
        assert "What's my hit points?" in DIRECT_INJECTION_FOURTH_WALL
        assert "Can I see the map?" in DIRECT_INJECTION_FOURTH_WALL

    def test_contradictory_inputs(self):
        assert (
            "I both leave and stay at the same time" in DIRECT_INJECTION_CONTRADICTORY
        )

    def test_all_pool_is_union(self):
        expected = (
            DIRECT_INJECTION_SHORT
            + DIRECT_INJECTION_NONSENSE
            + DIRECT_INJECTION_FOURTH_WALL
            + DIRECT_INJECTION_CONTRADICTORY
        )
        assert DIRECT_INJECTION_ALL == expected

    def test_all_pool_nonempty(self):
        assert len(DIRECT_INJECTION_ALL) > 0
        for item in DIRECT_INJECTION_ALL:
            assert isinstance(item, str)
            assert len(item) > 0


class TestPlaytestConfigEdgeCaseFields:
    def test_custom_frequencies(self):
        config = PlaytestConfig(
            game_id="test",
            direct_edge_case_frequency=0.10,
            nonsense_frequency=0.05,
            repeat_frequency=0.08,
        )
        assert config.direct_edge_case_frequency == 0.10
        assert config.nonsense_frequency == 0.05
        assert config.repeat_frequency == 0.08


# -- Golden Scenario Framework (offline tests) ------------------------------


class TestGoldenScenarioLoadScenario:
    def test_loads_yaml(self, tmp_path: Path):
        from scripts.run_golden import load_scenario

        scenario_data = {
            "name": "Test Scenario",
            "description": "A test",
            "game": "test-game",
            "turns": [
                {"input": None, "expect": {"narrator_not_empty": True}},
                {"input": "hello", "expect": {"narrator_not_empty": True}},
            ],
        }
        path = tmp_path / "test.yaml"
        with open(path, "w") as f:
            yaml.dump(scenario_data, f)

        loaded = load_scenario(path)
        assert loaded["name"] == "Test Scenario"
        assert loaded["game"] == "test-game"
        assert len(loaded["turns"]) == 2


class TestGoldenScenarioEvaluateAssertions:
    def test_narrator_not_empty_pass(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Some text here.")
        failures = evaluate_assertions(result, {"narrator_not_empty": True})
        assert failures == []

    def test_narrator_not_empty_fail(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="")
        failures = evaluate_assertions(result, {"narrator_not_empty": True})
        assert len(failures) == 1
        assert "narrator_not_empty" in failures[0]

    def test_narrator_word_count_min_pass(self):
        from scripts.run_golden import evaluate_assertions

        text = " ".join(["word"] * 60)
        result = _make_turn_result(narration=text)
        failures = evaluate_assertions(result, {"narrator_word_count_min": 50})
        assert failures == []

    def test_narrator_word_count_min_fail(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Just a few words.")
        failures = evaluate_assertions(result, {"narrator_word_count_min": 50})
        assert len(failures) == 1
        assert "narrator_word_count_min" in failures[0]

    def test_narrator_word_count_max_pass(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Short text here.")
        failures = evaluate_assertions(result, {"narrator_word_count_max": 100})
        assert failures == []

    def test_narrator_word_count_max_fail(self):
        from scripts.run_golden import evaluate_assertions

        text = " ".join(["word"] * 150)
        result = _make_turn_result(narration=text)
        failures = evaluate_assertions(result, {"narrator_word_count_max": 100})
        assert len(failures) == 1
        assert "narrator_word_count_max" in failures[0]

    def test_characters_responded_min_pass(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(
            narration="Some text.",
            characters=[CharacterResponse(character="Maya Chen", response="Hi.")],
        )
        failures = evaluate_assertions(result, {"characters_responded_min": 1})
        assert failures == []

    def test_characters_responded_min_fail(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Some text.")
        failures = evaluate_assertions(result, {"characters_responded_min": 1})
        assert len(failures) == 1
        assert "characters_responded_min" in failures[0]

    def test_characters_responded_max_pass(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(
            narration="Some text.",
            characters=[CharacterResponse(character="Maya Chen", response="Hi.")],
        )
        failures = evaluate_assertions(result, {"characters_responded_max": 2})
        assert failures == []

    def test_characters_responded_max_fail(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(
            narration="Some text.",
            characters=[
                CharacterResponse(character="Maya Chen", response="Hi."),
                CharacterResponse(character="Joaquin", response="Hello."),
                CharacterResponse(character="Extra", response="Hey."),
            ],
        )
        failures = evaluate_assertions(result, {"characters_responded_max": 2})
        assert len(failures) == 1
        assert "characters_responded_max" in failures[0]

    def test_characters_responded_includes_pass(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Some text.")
        # Override responding_characters on the narrator
        result.narrator.responding_characters = ["maya", "joaquin"]
        failures = evaluate_assertions(
            result, {"characters_responded_includes": ["maya"]}
        )
        assert failures == []

    def test_characters_responded_includes_fail(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Some text.")
        result.narrator.responding_characters = ["maya"]
        failures = evaluate_assertions(
            result, {"characters_responded_includes": ["joaquin"]}
        )
        assert len(failures) == 1
        assert "characters_responded_includes" in failures[0]

    def test_beats_hit_any_pass(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(
            narration="Some text.", beats_hit=["Player wakes up"]
        )
        failures = evaluate_assertions(result, {"beats_hit_any": True})
        assert failures == []

    def test_beats_hit_any_fail(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Some text.")
        failures = evaluate_assertions(result, {"beats_hit_any": True})
        assert len(failures) == 1
        assert "beats_hit_any" in failures[0]

    def test_beats_hit_count_min_pass(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(
            narration="Some text.",
            beats_hit=["Beat 1", "Beat 2"],
        )
        failures = evaluate_assertions(result, {"beats_hit_count_min": 2})
        assert failures == []

    def test_beats_hit_count_min_fail(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Some text.", beats_hit=["Beat 1"])
        failures = evaluate_assertions(result, {"beats_hit_count_min": 2})
        assert len(failures) == 1
        assert "beats_hit_count_min" in failures[0]

    def test_no_assertions_no_failures(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Some text.")
        failures = evaluate_assertions(result, {})
        assert failures == []

    def test_multiple_assertions(self):
        from scripts.run_golden import evaluate_assertions

        result = _make_turn_result(narration="Short.")
        failures = evaluate_assertions(
            result,
            {
                "narrator_not_empty": True,
                "narrator_word_count_min": 100,
                "characters_responded_min": 1,
            },
        )
        # narrator_not_empty passes, but word_count_min and characters_responded_min fail
        assert len(failures) == 2


class TestGoldenScenarioFiles:
    """Verify the golden scenario YAML files are valid."""

    SCENARIOS_DIR = Path(__file__).parent / "golden_scenarios"

    def test_scenarios_dir_exists(self):
        assert self.SCENARIOS_DIR.exists()

    def test_all_scenarios_load(self):
        from scripts.run_golden import load_scenario

        for path in sorted(self.SCENARIOS_DIR.glob("*.yaml")):
            scenario = load_scenario(path)
            assert "name" in scenario, f"{path.name}: missing 'name'"
            assert "game" in scenario, f"{path.name}: missing 'game'"
            assert "turns" in scenario, f"{path.name}: missing 'turns'"
            assert len(scenario["turns"]) > 0, f"{path.name}: no turns defined"

    def test_expected_scenarios_present(self):
        names = {p.stem for p in self.SCENARIOS_DIR.glob("*.yaml")}
        expected = {
            "crash_opening",
            "maya_dialogue",
            "short_input",
            "adversarial_input",
            "both_characters",
        }
        assert expected.issubset(names), f"Missing scenarios: {expected - names}"

    def test_all_scenarios_reference_valid_game(self):
        from scripts.run_golden import load_scenario

        for path in sorted(self.SCENARIOS_DIR.glob("*.yaml")):
            scenario = load_scenario(path)
            assert scenario["game"] == "lost-island", (
                f"{path.name}: unexpected game '{scenario['game']}'"
            )

    def test_all_turns_have_expect(self):
        from scripts.run_golden import load_scenario

        for path in sorted(self.SCENARIOS_DIR.glob("*.yaml")):
            scenario = load_scenario(path)
            for i, turn in enumerate(scenario["turns"]):
                assert "expect" in turn, f"{path.name}: turn {i} missing 'expect'"
