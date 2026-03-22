"""Tests for public helper functions in creator session module."""

from __future__ import annotations

from theact.creator.session import (
    chap_info_from_data,
    char_info_from_data,
    next_chapter_id,
    proposal_from_data,
)

# --- Sample generated game data ---

SAMPLE_DATA = {
    "game": {
        "id": "test-game",
        "title": "Test Game",
    },
    "world": {
        "setting": "A dark forest",
        "tone": "Grim and foreboding",
        "rules": "Stay on the path",
    },
    "characters": {
        "alice": {"name": "Alice", "role": "Guide"},
        "bob": {"name": "Bob", "role": "Trickster"},
    },
    "chapters": {
        "01-start": {"title": "The Beginning", "summary": "You wake up."},
        "02-middle": {"title": "The Journey", "summary": "You travel."},
        "03-end": {"title": "The End", "summary": "You arrive."},
    },
}


class TestProposalFromData:
    def test_extracts_title_and_id(self):
        proposal = proposal_from_data(SAMPLE_DATA)
        assert proposal["title"] == "Test Game"
        assert proposal["id"] == "test-game"

    def test_extracts_setting_from_world(self):
        proposal = proposal_from_data(SAMPLE_DATA)
        assert proposal["setting"] == "A dark forest"
        assert proposal["tone"] == "Grim and foreboding"

    def test_extracts_characters_as_list(self):
        proposal = proposal_from_data(SAMPLE_DATA)
        chars = proposal["characters"]
        assert len(chars) == 2
        stems = [c["stem"] for c in chars]
        assert "alice" in stems
        assert "bob" in stems

    def test_extracts_chapters_as_list(self):
        proposal = proposal_from_data(SAMPLE_DATA)
        chaps = proposal["chapters"]
        assert len(chaps) == 3
        ids = [c["id"] for c in chaps]
        assert "01-start" in ids

    def test_handles_empty_data(self):
        proposal = proposal_from_data({})
        assert proposal["title"] == ""
        assert proposal["characters"] == []
        assert proposal["chapters"] == []


class TestCharInfoFromData:
    def test_returns_char_info(self):
        info = char_info_from_data(SAMPLE_DATA, "alice")
        assert info == {"stem": "alice", "name": "Alice", "role": "Guide"}

    def test_returns_none_for_missing(self):
        assert char_info_from_data(SAMPLE_DATA, "nonexistent") is None

    def test_defaults_name_to_stem(self):
        data = {"characters": {"unnamed": {"role": "Mystery"}}}
        info = char_info_from_data(data, "unnamed")
        assert info["name"] == "unnamed"


class TestChapInfoFromData:
    def test_returns_chap_info(self):
        info = chap_info_from_data(SAMPLE_DATA, "01-start")
        assert info == {
            "id": "01-start",
            "title": "The Beginning",
            "summary": "You wake up.",
        }

    def test_returns_none_for_missing(self):
        assert chap_info_from_data(SAMPLE_DATA, "nonexistent") is None


class TestNextChapterId:
    def test_returns_next_chapter(self):
        assert next_chapter_id(SAMPLE_DATA, "01-start") == "02-middle"
        assert next_chapter_id(SAMPLE_DATA, "02-middle") == "03-end"

    def test_returns_none_for_last_chapter(self):
        assert next_chapter_id(SAMPLE_DATA, "03-end") is None

    def test_returns_none_for_missing_chapter(self):
        assert next_chapter_id(SAMPLE_DATA, "nonexistent") is None
