"""Tests for Pydantic data models."""

import pytest
from pydantic import ValidationError

from theact.models import (
    Chapter,
    ChapterSummary,
    Character,
    CharacterMemory,
    ConversationEntry,
    GameMeta,
    GameState,
    World,
)


# --- World ---


class TestWorld:
    def test_valid(self, sample_world_data: dict):
        world = World(**sample_world_data)
        assert world.setting == sample_world_data["setting"]
        assert world.tone == sample_world_data["tone"]
        assert world.rules == sample_world_data["rules"]

    def test_rejects_extra_fields(self, sample_world_data: dict):
        sample_world_data["mood"] = "spooky"
        with pytest.raises(ValidationError, match="mood"):
            World(**sample_world_data)

    def test_requires_all_fields(self):
        with pytest.raises(ValidationError):
            World(setting="here", tone="dark")


# --- Character ---


class TestCharacter:
    def test_valid(self, sample_character_data: dict):
        char = Character(**sample_character_data)
        assert char.name == "Elena"
        assert "brother" in char.relationships

    def test_rejects_extra_fields(self, sample_character_data: dict):
        sample_character_data["age"] = 30
        with pytest.raises(ValidationError, match="age"):
            Character(**sample_character_data)

    def test_empty_relationships(self, sample_character_data: dict):
        sample_character_data["relationships"] = {}
        char = Character(**sample_character_data)
        assert char.relationships == {}


# --- Chapter ---


class TestChapter:
    def test_valid(self, sample_chapter_data: dict):
        chap = Chapter(**sample_chapter_data)
        assert chap.id == "01-arrival"
        assert chap.next == "02-the-market"
        assert len(chap.beats) == 3

    def test_next_defaults_none(self, sample_chapter_data: dict):
        del sample_chapter_data["next"]
        chap = Chapter(**sample_chapter_data)
        assert chap.next is None

    def test_rejects_extra_fields(self, sample_chapter_data: dict):
        sample_chapter_data["difficulty"] = "hard"
        with pytest.raises(ValidationError, match="difficulty"):
            Chapter(**sample_chapter_data)


class TestChapterSummary:
    def test_valid(self):
        cs = ChapterSummary(
            chapter_id="01-arrival",
            title="The Arrival",
            summary="Player arrived and entered the village.",
        )
        assert cs.chapter_id == "01-arrival"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError, match="rating"):
            ChapterSummary(
                chapter_id="01",
                title="X",
                summary="Y",
                rating=5,
            )


# --- GameState ---


class TestGameState:
    def test_valid(self, sample_state_data: dict):
        state = GameState(**sample_state_data)
        assert state.turn == 3
        assert state.player_name == "Alex"

    def test_rolling_summary_defaults_empty(self, sample_state_data: dict):
        del sample_state_data["rolling_summary"]
        state = GameState(**sample_state_data)
        assert state.rolling_summary == ""

    def test_rejects_extra_fields(self, sample_state_data: dict):
        sample_state_data["health"] = 100
        with pytest.raises(ValidationError, match="health"):
            GameState(**sample_state_data)


# --- ConversationEntry ---


class TestConversationEntry:
    def test_valid_narrator(self, sample_conversation_entry_data: dict):
        entry = ConversationEntry(**sample_conversation_entry_data)
        assert entry.role == "narrator"
        assert entry.character is None

    def test_valid_character(self):
        entry = ConversationEntry(
            turn=2, role="character", character="Elena", content="Hello traveler."
        )
        assert entry.character == "Elena"

    def test_valid_player(self):
        entry = ConversationEntry(turn=1, role="player", content="I look around.")
        assert entry.role == "player"

    def test_invalid_role(self):
        with pytest.raises(ValidationError, match="role"):
            ConversationEntry(turn=1, role="enemy", content="Attack!")

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError, match="mood"):
            ConversationEntry(turn=1, role="narrator", content="Hello.", mood="happy")


# --- CharacterMemory ---


class TestCharacterMemory:
    def test_valid(self, sample_memory_data: dict):
        mem = CharacterMemory(**sample_memory_data)
        assert mem.character == "Elena"
        assert len(mem.key_facts) == 2

    def test_rejects_extra_fields(self, sample_memory_data: dict):
        sample_memory_data["trust_level"] = 5
        with pytest.raises(ValidationError, match="trust_level"):
            CharacterMemory(**sample_memory_data)


# --- GameMeta ---


class TestGameMeta:
    def test_valid(self, sample_game_meta_data: dict):
        meta = GameMeta(**sample_game_meta_data)
        assert meta.id == "test-game"
        assert "elena" in meta.characters

    def test_rejects_extra_fields(self, sample_game_meta_data: dict):
        sample_game_meta_data["version"] = "1.0"
        with pytest.raises(ValidationError, match="version"):
            GameMeta(**sample_game_meta_data)
