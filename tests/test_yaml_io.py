"""Tests for YAML I/O helpers."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from theact.io.yaml_io import (
    append_yaml_entry,
    dump_yaml,
    dump_yaml_list,
    load_yaml,
    load_yaml_list,
)
from theact.models import (
    Chapter,
    Character,
    CharacterMemory,
    ConversationEntry,
    GameState,
    World,
)


class TestLoadDumpYaml:
    """Test single-model YAML round-trips."""

    def test_world_roundtrip(self, tmp_path: Path, sample_world_data: dict):
        path = tmp_path / "world.yaml"
        world = World(**sample_world_data)
        dump_yaml(path, world)
        loaded = load_yaml(path, World)
        assert loaded == world

    def test_character_roundtrip(self, tmp_path: Path, sample_character_data: dict):
        path = tmp_path / "char.yaml"
        char = Character(**sample_character_data)
        dump_yaml(path, char)
        loaded = load_yaml(path, Character)
        assert loaded == char

    def test_chapter_roundtrip(self, tmp_path: Path, sample_chapter_data: dict):
        path = tmp_path / "chap.yaml"
        chap = Chapter(**sample_chapter_data)
        dump_yaml(path, chap)
        loaded = load_yaml(path, Chapter)
        assert loaded == chap

    def test_chapter_no_next_excludes_none(
        self, tmp_path: Path, sample_chapter_data: dict
    ):
        """When next=None, dump_yaml should exclude it (exclude_none=True)."""
        sample_chapter_data["next"] = None
        path = tmp_path / "chap.yaml"
        chap = Chapter(**sample_chapter_data)
        dump_yaml(path, chap)
        loaded = load_yaml(path, Chapter)
        assert loaded.next is None

    def test_state_roundtrip(self, tmp_path: Path, sample_state_data: dict):
        path = tmp_path / "state.yaml"
        state = GameState(**sample_state_data)
        dump_yaml(path, state)
        loaded = load_yaml(path, GameState)
        assert loaded == state

    def test_memory_roundtrip(self, tmp_path: Path, sample_memory_data: dict):
        path = tmp_path / "mem.yaml"
        mem = CharacterMemory(**sample_memory_data)
        dump_yaml(path, mem)
        loaded = load_yaml(path, CharacterMemory)
        assert loaded == mem

    def test_creates_parent_dirs(self, tmp_path: Path, sample_world_data: dict):
        path = tmp_path / "sub" / "dir" / "world.yaml"
        world = World(**sample_world_data)
        dump_yaml(path, world)
        assert path.exists()

    def test_load_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_yaml(tmp_path / "nope.yaml", World)

    def test_load_invalid_data_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("setting: yes\n")
        with pytest.raises(ValidationError):
            load_yaml(path, World)


class TestLoadDumpYamlList:
    """Test list-based YAML round-trips."""

    def test_conversation_roundtrip(self, tmp_path: Path):
        path = tmp_path / "conv.yaml"
        entries = [
            ConversationEntry(turn=1, role="narrator", content="You wake up."),
            ConversationEntry(turn=1, role="player", content="I look around."),
            ConversationEntry(
                turn=1, role="character", character="Elena", content="Hello."
            ),
        ]
        dump_yaml_list(path, entries)
        loaded = load_yaml_list(path, ConversationEntry)
        assert loaded == entries

    def test_empty_list(self, tmp_path: Path):
        path = tmp_path / "empty.yaml"
        dump_yaml_list(path, [])
        loaded = load_yaml_list(path, ConversationEntry)
        assert loaded == []

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "list.yaml"
        dump_yaml_list(path, [])
        assert path.exists()


class TestAppendYamlEntry:
    """Test appending entries to YAML list files."""

    def test_creates_file_if_missing(self, tmp_path: Path):
        path = tmp_path / "conv.yaml"
        entry = ConversationEntry(turn=1, role="narrator", content="Hello.")
        append_yaml_entry(path, entry)
        loaded = load_yaml_list(path, ConversationEntry)
        assert len(loaded) == 1
        assert loaded[0] == entry

    def test_appends_to_existing(self, tmp_path: Path):
        path = tmp_path / "conv.yaml"
        e1 = ConversationEntry(turn=1, role="narrator", content="First.")
        e2 = ConversationEntry(turn=1, role="player", content="Second.")
        append_yaml_entry(path, e1)
        append_yaml_entry(path, e2)
        loaded = load_yaml_list(path, ConversationEntry)
        assert len(loaded) == 2
        assert loaded[0] == e1
        assert loaded[1] == e2

    def test_appends_to_empty_file(self, tmp_path: Path):
        path = tmp_path / "conv.yaml"
        path.write_text("")  # Empty file
        entry = ConversationEntry(turn=1, role="narrator", content="Hello.")
        append_yaml_entry(path, entry)
        loaded = load_yaml_list(path, ConversationEntry)
        assert len(loaded) == 1

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "conv.yaml"
        entry = ConversationEntry(turn=1, role="narrator", content="Hello.")
        append_yaml_entry(path, entry)
        assert path.exists()


class TestSpecialCharacters:
    """Test YAML round-trips with special characters that could break serialization."""

    def test_colon_in_content(self, tmp_path: Path):
        path = tmp_path / "conv.yaml"
        entry = ConversationEntry(turn=1, role="player", content="Where are we: lost?")
        append_yaml_entry(path, entry)
        loaded = load_yaml_list(path, ConversationEntry)
        assert loaded[0].content == "Where are we: lost?"

    def test_quotes_in_content(self, tmp_path: Path):
        path = tmp_path / "conv.yaml"
        entry = ConversationEntry(
            turn=1, role="player", content="She said \"run\" and he said 'no'."
        )
        append_yaml_entry(path, entry)
        loaded = load_yaml_list(path, ConversationEntry)
        assert loaded[0].content == "She said \"run\" and he said 'no'."

    def test_newlines_in_content(self, tmp_path: Path):
        path = tmp_path / "conv.yaml"
        entry = ConversationEntry(
            turn=1, role="narrator", content="Line one.\nLine two.\nLine three."
        )
        append_yaml_entry(path, entry)
        loaded = load_yaml_list(path, ConversationEntry)
        assert loaded[0].content == "Line one.\nLine two.\nLine three."

    def test_unicode_in_content(self, tmp_path: Path):
        path = tmp_path / "conv.yaml"
        entry = ConversationEntry(
            turn=1,
            role="narrator",
            content="The sign reads: \u201cBienvenue\u201d \u2014 welcome.",
        )
        append_yaml_entry(path, entry)
        loaded = load_yaml_list(path, ConversationEntry)
        assert "\u201c" in loaded[0].content

    def test_long_content(self, tmp_path: Path):
        """Test with 500+ word player input."""
        path = tmp_path / "conv.yaml"
        long_text = " ".join(["word"] * 600)
        entry = ConversationEntry(turn=1, role="player", content=long_text)
        append_yaml_entry(path, entry)
        loaded = load_yaml_list(path, ConversationEntry)
        assert loaded[0].content == long_text


class TestExampleGameFiles:
    """Test that the example game files load correctly through the YAML I/O layer."""

    GAMES_DIR = Path(__file__).parent.parent / "games" / "lost-island"

    def test_load_game_meta(self):
        from theact.models import GameMeta

        meta = load_yaml(self.GAMES_DIR / "game.yaml", GameMeta)
        assert meta.id == "lost-island"
        assert len(meta.characters) == 2
        assert len(meta.chapters) == 3

    def test_load_world(self):
        world = load_yaml(self.GAMES_DIR / "world.yaml", World)
        assert "South Pacific" in world.setting
        assert "second person" in world.tone.lower()

    def test_load_maya(self):
        char = load_yaml(self.GAMES_DIR / "characters" / "maya.yaml", Character)
        assert char.name == "Maya Chen"
        assert "joaquin" in char.relationships

    def test_load_joaquin(self):
        char = load_yaml(self.GAMES_DIR / "characters" / "joaquin.yaml", Character)
        assert char.name == "Father Joaquin Reyes"

    def test_load_chapter(self):
        chap = load_yaml(self.GAMES_DIR / "chapters" / "01-the-crash.yaml", Chapter)
        assert chap.id == "01-the-crash"
        assert chap.next == "02-the-discovery"
        assert len(chap.beats) == 6
