"""Tests for creator file writer."""

from pathlib import Path

import pytest

from theact.creator.validator import validate_game_data
from theact.creator.writer import write_game_files
from theact.io.yaml_io import load_yaml
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.game import GameMeta
from theact.models.world import World


def _valid_game_data() -> dict:
    """A fully valid game data dict."""
    return {
        "game": {
            "id": "writer-test",
            "title": "Writer Test",
            "description": "Testing the writer.",
            "characters": ["maya"],
            "chapters": ["01-start"],
        },
        "world": {
            "setting": "A dark forest.",
            "tone": "Second person, present tense.",
            "rules": "No magic allowed.",
        },
        "characters": {
            "maya": {
                "name": "Maya",
                "role": "Guide through the forest.",
                "personality": "Calm and focused. Speaks in short sentences.",
                "secret": "Knows the way out already.",
                "relationships": {},
            },
        },
        "chapters": {
            "01-start": {
                "id": "01-start",
                "title": "The Start",
                "summary": "Enter the forest and meet Maya.",
                "beats": [
                    "Player enters the forest",
                    "Discovers strange markings",
                    "Meets Maya at a clearing",
                    "Maya offers to guide",
                ],
                "completion": "Player has agreed to follow Maya.",
                "characters": ["maya"],
                "next": None,
            },
        },
    }


class TestWriteGameFiles:
    def test_creates_all_files(self, tmp_path: Path):
        data = _valid_game_data()
        result = validate_game_data(data)
        assert result.valid

        game_path = write_game_files("writer-test", result, games_dir=tmp_path)

        assert game_path == tmp_path / "writer-test"
        assert (game_path / "game.yaml").exists()
        assert (game_path / "world.yaml").exists()
        assert (game_path / "characters" / "maya.yaml").exists()
        assert (game_path / "chapters" / "01-start.yaml").exists()

    def test_written_files_validate(self, tmp_path: Path):
        data = _valid_game_data()
        result = validate_game_data(data)
        assert result.valid

        game_path = write_game_files("writer-test", result, games_dir=tmp_path)

        # Load back and validate against Pydantic models
        meta = load_yaml(game_path / "game.yaml", GameMeta)
        assert meta.id == "writer-test"
        assert meta.characters == ["maya"]

        world = load_yaml(game_path / "world.yaml", World)
        assert "forest" in world.setting.lower()

        char = load_yaml(game_path / "characters" / "maya.yaml", Character)
        assert char.name == "Maya"

        chap = load_yaml(game_path / "chapters" / "01-start.yaml", Chapter)
        assert chap.id == "01-start"
        assert chap.next is None

    def test_raises_on_existing_dir(self, tmp_path: Path):
        data = _valid_game_data()
        result = validate_game_data(data)
        assert result.valid

        # Create the directory first
        (tmp_path / "writer-test").mkdir()

        with pytest.raises(FileExistsError, match="already exists"):
            write_game_files("writer-test", result, games_dir=tmp_path)

    def test_overwrite_existing_dir(self, tmp_path: Path):
        data = _valid_game_data()
        result = validate_game_data(data)
        assert result.valid

        # Create the directory first
        (tmp_path / "writer-test").mkdir()

        # Should succeed with overwrite=True
        game_path = write_game_files(
            "writer-test", result, overwrite=True, games_dir=tmp_path
        )
        assert (game_path / "game.yaml").exists()

    def test_directory_structure_matches_spec(self, tmp_path: Path):
        """The created structure should match Phase 01 spec: game.yaml,
        world.yaml, characters/*.yaml, chapters/*.yaml."""
        data = _valid_game_data()
        result = validate_game_data(data)
        assert result.valid

        game_path = write_game_files("writer-test", result, games_dir=tmp_path)

        # Check top-level files
        top_files = {f.name for f in game_path.iterdir() if f.is_file()}
        assert "game.yaml" in top_files
        assert "world.yaml" in top_files

        # Check subdirectories
        subdirs = {d.name for d in game_path.iterdir() if d.is_dir()}
        assert "characters" in subdirs
        assert "chapters" in subdirs

    def test_multiple_characters_and_chapters(self, tmp_path: Path):
        data = _valid_game_data()
        # Add a second character and chapter
        data["characters"]["elena"] = {
            "name": "Elena",
            "role": "Doctor.",
            "personality": "Precise.",
            "secret": "Immune.",
            "relationships": {"maya": "Skeptical."},
        }
        data["characters"]["maya"]["relationships"]["elena"] = "Curious."
        data["game"]["characters"].append("elena")

        data["chapters"]["02-end"] = {
            "id": "02-end",
            "title": "The End",
            "summary": "The conclusion.",
            "beats": [
                "Final confrontation",
                "Resolution",
                "Epilogue",
                "Credits roll",
            ],
            "completion": "Story is complete.",
            "characters": ["maya", "elena"],
            "next": None,
        }
        data["chapters"]["01-start"]["next"] = "02-end"
        data["game"]["chapters"].append("02-end")

        result = validate_game_data(data)
        assert result.valid

        game_path = write_game_files("writer-test", result, games_dir=tmp_path)

        assert (game_path / "characters" / "maya.yaml").exists()
        assert (game_path / "characters" / "elena.yaml").exists()
        assert (game_path / "chapters" / "01-start.yaml").exists()
        assert (game_path / "chapters" / "02-end.yaml").exists()
