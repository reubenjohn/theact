"""Tests for engine result types (dataclasses)."""

from theact.engine.types import (
    CharacterResponse,
    GameStateResult,
    MemoryDiff,
    NarratorOutput,
    TurnResult,
)


class TestNarratorOutput:
    def test_construction(self):
        out = NarratorOutput(
            narration="You step into the clearing.",
            responding_characters=["maya", "joaquin"],
            mood="tense",
        )
        assert out.narration == "You step into the clearing."
        assert out.responding_characters == ["maya", "joaquin"]
        assert out.mood == "tense"

    def test_empty_characters(self):
        out = NarratorOutput(
            narration="Silence.",
            responding_characters=[],
            mood="calm",
        )
        assert out.responding_characters == []


class TestCharacterResponse:
    def test_construction(self):
        resp = CharacterResponse(
            character="Maya Chen",
            response="She sets down the wrench.",
        )
        assert resp.character == "Maya Chen"
        assert resp.response == "She sets down the wrench."

    def test_thinking_default(self):
        resp = CharacterResponse(
            character="Maya",
            response="Hello.",
        )
        assert resp.thinking is None

    def test_thinking_provided(self):
        resp = CharacterResponse(
            character="Maya",
            response="Hello.",
            thinking="I should greet them.",
        )
        assert resp.thinking == "I should greet them."


class TestMemoryDiff:
    def test_construction(self):
        diff = MemoryDiff(
            character="Maya Chen",
            old_summary="Met the player.",
            new_summary="Met the player on the beach. They seem trustworthy.",
            old_facts=["Player arrived alone"],
            new_facts=["Player arrived alone", "Player found a lighter"],
        )
        assert diff.character == "Maya Chen"
        assert diff.new_summary == "Met the player on the beach. They seem trustworthy."
        assert len(diff.new_facts) == 2

    def test_defaults(self):
        diff = MemoryDiff(
            character="Maya",
            old_summary="",
            new_summary="",
        )
        assert diff.old_facts == []
        assert diff.new_facts == []


class TestGameStateResult:
    def test_construction(self):
        result = GameStateResult(
            beats_hit=["Player wakes on the beach"],
            completed=True,
            reasoning="All beats have been hit.",
        )
        assert result.completed is True
        assert result.beats_hit == ["Player wakes on the beach"]
        assert result.reasoning == "All beats have been hit."

    def test_defaults(self):
        result = GameStateResult()
        assert result.beats_hit == []
        assert result.completed is False
        assert result.reasoning is None


class TestTurnResult:
    def test_construction(self):
        narrator = NarratorOutput(
            narration="You wake up.",
            responding_characters=["maya"],
            mood="calm",
        )
        char_resp = CharacterResponse(
            character="Maya Chen",
            response="She looks at you.",
        )
        diff = MemoryDiff(
            character="Maya Chen",
            old_summary="",
            new_summary="Met the player.",
            old_facts=[],
            new_facts=["Player is disoriented"],
        )
        state = GameStateResult(
            beats_hit=["Player wakes on the beach"],
            completed=False,
        )

        result = TurnResult(
            turn=1,
            narrator=narrator,
            characters=[char_resp],
            memory_diffs=[diff],
            game_state=state,
        )

        assert result.turn == 1
        assert result.narrator.narration == "You wake up."
        assert len(result.characters) == 1
        assert len(result.memory_diffs) == 1
        assert result.game_state is not None
        assert result.game_state.completed is False

    def test_defaults(self):
        narrator = NarratorOutput(
            narration="Silence.",
            responding_characters=[],
            mood="calm",
        )
        result = TurnResult(
            turn=1,
            narrator=narrator,
            characters=[],
            memory_diffs=[],
        )
        assert result.game_state is None
        assert result.chapter_advanced is False
        assert result.new_chapter is None
        assert result.summary_updated is False
