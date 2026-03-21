"""Tests for the game meta assembler and consistency enforcement."""

from theact.creator.assembler import (
    assemble_game_meta,
    assemble_game_meta_from_data,
    enforce_consistency,
)


class TestAssembleGameMeta:
    def test_basic_assembly(self):
        proposal = {"id": "test-game", "title": "Test Game"}
        characters = {"maya": {"name": "Maya"}, "jake": {"name": "Jake"}}
        chapters = {"01-start": {}, "02-end": {}}

        result = assemble_game_meta(proposal, characters, chapters)
        assert result["id"] == "test-game"
        assert result["title"] == "Test Game"
        assert result["characters"] == ["maya", "jake"]
        assert result["chapters"] == ["01-start", "02-end"]
        assert "description" in result

    def test_empty_characters(self):
        proposal = {"id": "test", "title": "Test"}
        result = assemble_game_meta(proposal, {}, {"01-x": {}})
        assert result["characters"] == []


class TestAssembleGameMetaFromData:
    def test_rebuilds_from_data(self):
        data = {
            "game": {"id": "test", "title": "Test", "description": "A game."},
            "characters": {"maya": {}, "jake": {}},
            "chapters": {"01-x": {}, "02-y": {}},
        }
        result = assemble_game_meta_from_data(data)
        assert result["characters"] == ["maya", "jake"]
        assert result["chapters"] == ["01-x", "02-y"]

    def test_creates_description_if_missing(self):
        data = {
            "game": {"id": "t", "title": "T"},
            "characters": {},
            "chapters": {},
        }
        result = assemble_game_meta_from_data(data)
        assert "T" in result["description"]


class TestEnforceConsistency:
    def test_removes_self_referencing_relationships(self):
        data = {
            "game": {"id": "t", "title": "T"},
            "world": {},
            "characters": {
                "maya": {
                    "name": "Maya",
                    "relationships": {"maya": "self", "jake": "friend"},
                },
                "jake": {"name": "Jake", "relationships": {"maya": "ally"}},
            },
            "chapters": {},
        }
        result = enforce_consistency(data)
        assert "maya" not in result["characters"]["maya"]["relationships"]
        assert "jake" in result["characters"]["maya"]["relationships"]

    def test_strips_invalid_character_stems_from_chapters(self):
        data = {
            "game": {"id": "t", "title": "T"},
            "world": {},
            "characters": {"maya": {"name": "Maya", "relationships": {}}},
            "chapters": {"01-x": {"characters": ["maya", "nonexistent"], "next": None}},
        }
        result = enforce_consistency(data)
        assert result["chapters"]["01-x"]["characters"] == ["maya"]

    def test_strips_invalid_relationship_stems(self):
        data = {
            "game": {"id": "t", "title": "T"},
            "world": {},
            "characters": {
                "maya": {"name": "Maya", "relationships": {"nonexistent": "enemy"}},
            },
            "chapters": {},
        }
        result = enforce_consistency(data)
        assert result["characters"]["maya"]["relationships"] == {}

    def test_rewires_chapter_next_chain(self):
        data = {
            "game": {"id": "t", "title": "T"},
            "world": {},
            "characters": {},
            "chapters": {
                "01-x": {"next": "wrong"},
                "02-y": {"next": "also-wrong"},
                "03-z": {"next": "should-be-null"},
            },
        }
        result = enforce_consistency(data)
        assert result["chapters"]["01-x"]["next"] == "02-y"
        assert result["chapters"]["02-y"]["next"] == "03-z"
        assert result["chapters"]["03-z"]["next"] is None

    def test_rebuilds_game_meta(self):
        data = {
            "game": {"id": "t", "title": "T", "characters": [], "chapters": []},
            "world": {},
            "characters": {"maya": {"name": "Maya", "relationships": {}}},
            "chapters": {"01-x": {"characters": ["maya"], "next": None}},
        }
        result = enforce_consistency(data)
        assert result["game"]["characters"] == ["maya"]
        assert result["game"]["chapters"] == ["01-x"]

    def test_does_not_mutate_input(self):
        data = {
            "game": {"id": "t", "title": "T"},
            "world": {},
            "characters": {"maya": {"name": "Maya", "relationships": {"maya": "self"}}},
            "chapters": {},
        }
        original_rels = dict(data["characters"]["maya"]["relationships"])
        enforce_consistency(data)
        assert data["characters"]["maya"]["relationships"] == original_rels
