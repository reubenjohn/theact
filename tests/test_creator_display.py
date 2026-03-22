"""Tests for creator display helpers (Rich-formatted output)."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from rich.console import Console

from theact.creator.display import (
    display_game_files,
    display_proposal,
    display_size_warnings,
    display_validation_errors,
)
from theact.creator.validator import ValidationError, ValidationResult
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.game import GameMeta
from theact.models.world import World


def _capture_console_output(func, *args) -> str:
    """Run a display function with a captured console and return the output."""
    buf = StringIO()
    fake_console = Console(file=buf, force_terminal=True, width=120)
    with patch("theact.creator.display.console", fake_console):
        func(*args)
    return buf.getvalue()


class TestDisplayProposal:
    def test_full_proposal_with_dict_characters_and_chapters(self):
        proposal = {
            "title": "Dark Forest",
            "id": "dark-forest",
            "setting": "A dark forest at dusk.",
            "tone": "Second person, present tense.",
            "rules": "No magic allowed.",
            "characters": [
                {"name": "Maya", "role": "Guide"},
                {"name": "Jake", "role": "Survivor"},
            ],
            "chapters": [
                {"id": "01-start", "title": "The Start", "summary": "Begin."},
                {"id": "02-end", "title": "The End", "summary": "Finish."},
            ],
        }
        output = _capture_console_output(display_proposal, proposal)
        assert "Dark Forest" in output
        assert "dark-forest" in output
        assert "A dark forest at dusk." in output
        assert "Second person, present tense." in output
        assert "No magic allowed." in output
        assert "Maya" in output
        assert "Guide" in output
        assert "Jake" in output
        assert "The Start" in output
        assert "01-start" in output
        assert "Begin." in output
        assert "GAME PROPOSAL" in output

    def test_proposal_with_string_characters_and_chapters(self):
        proposal = {
            "title": "Test",
            "id": "test",
            "characters": ["Maya the Guide", "Jake the Survivor"],
            "chapters": ["Chapter 1", "Chapter 2"],
        }
        output = _capture_console_output(display_proposal, proposal)
        assert "Maya the Guide" in output
        assert "Jake the Survivor" in output
        assert "Chapter 1" in output
        assert "Chapter 2" in output

    def test_minimal_proposal_no_optional_fields(self):
        proposal = {"title": "Minimal", "id": "minimal"}
        output = _capture_console_output(display_proposal, proposal)
        assert "Minimal" in output
        assert "minimal" in output

    def test_empty_proposal_uses_defaults(self):
        proposal = {}
        output = _capture_console_output(display_proposal, proposal)
        assert "?" in output  # Falls back to "?" for missing title/id

    def test_proposal_with_empty_characters_and_chapters(self):
        proposal = {
            "title": "Test",
            "id": "test",
            "characters": [],
            "chapters": [],
        }
        output = _capture_console_output(display_proposal, proposal)
        assert "Test" in output
        # Empty lists should not produce character/chapter sections
        assert "Characters:" not in output
        assert "Chapters:" not in output


class TestDisplayGameFiles:
    def _make_result(self) -> ValidationResult:
        game = GameMeta(
            id="test-game",
            title="Test Game",
            description="A test game.",
            characters=["maya"],
            chapters=["01-start"],
        )
        world = World(
            setting="A dark forest.",
            tone="Second person, present tense.",
            rules="No magic.",
        )
        characters = {
            "maya": Character(
                name="Maya",
                role="Guide.",
                personality="Calm and focused.",
                secret="Knows the way out.",
                relationships={"jake": "Trusts him."},
            ),
        }
        chapters = {
            "01-start": Chapter(
                id="01-start",
                title="The Start",
                summary="Begin the journey.",
                beats=["Enter", "Walk", "Find", "Leave"],
                completion="Player exits.",
                characters=["maya"],
                next=None,
            ),
        }
        return ValidationResult(
            valid=True,
            errors=[],
            game=game,
            world=world,
            characters=characters,
            chapters=chapters,
        )

    def test_displays_all_file_sections(self):
        result = self._make_result()
        output = _capture_console_output(display_game_files, result)
        assert "game.yaml" in output
        assert "world.yaml" in output
        assert "characters/maya.yaml" in output
        assert "chapters/01-start.yaml" in output
        assert "Test Game" in output
        assert "A dark forest." in output
        assert "Maya" in output
        assert "The Start" in output

    def test_displays_character_relationships(self):
        result = self._make_result()
        output = _capture_console_output(display_game_files, result)
        assert "jake" in output
        assert "Trusts him." in output

    def test_displays_chapter_beats(self):
        result = self._make_result()
        output = _capture_console_output(display_game_files, result)
        assert "Enter" in output
        assert "Walk" in output

    def test_final_chapter_shows_marker(self):
        result = self._make_result()
        output = _capture_console_output(display_game_files, result)
        assert "(final chapter)" in output

    def test_no_game_skips_game_panel(self):
        result = ValidationResult(valid=False, errors=[])
        output = _capture_console_output(display_game_files, result)
        assert "game.yaml" not in output

    def test_no_world_skips_world_panel(self):
        result = self._make_result()
        result.world = None
        output = _capture_console_output(display_game_files, result)
        assert "world.yaml" not in output

    def test_chapter_with_next(self):
        result = self._make_result()
        # Add a second chapter to test non-None next
        result.chapters["01-start"] = Chapter(
            id="01-start",
            title="The Start",
            summary="Begin.",
            beats=["Enter", "Walk", "Find", "Leave"],
            completion="Done.",
            characters=["maya"],
            next="02-end",
        )
        output = _capture_console_output(display_game_files, result)
        assert "02-end" in output


class TestDisplayValidationErrors:
    def test_displays_errors_with_field(self):
        errors = [
            ValidationError("world.yaml", "setting", "Setting is missing"),
        ]
        output = _capture_console_output(display_validation_errors, errors)
        assert "world.yaml" in output
        assert "[setting]" in output
        assert "Setting is missing" in output
        assert "Validation Errors" in output

    def test_displays_errors_without_field(self):
        errors = [
            ValidationError("game.yaml", "", "Game YAML is invalid"),
        ]
        output = _capture_console_output(display_validation_errors, errors)
        assert "game.yaml" in output
        assert "Game YAML is invalid" in output
        # No field bracket when field is empty
        assert "[" not in output or "game.yaml:" in output

    def test_displays_multiple_errors(self):
        errors = [
            ValidationError("world.yaml", "setting", "Missing setting"),
            ValidationError("characters/maya.yaml", "secret", "Missing secret"),
            ValidationError("chapters/01-start.yaml", "beats", "Too few beats"),
        ]
        output = _capture_console_output(display_validation_errors, errors)
        assert "world.yaml" in output
        assert "characters/maya.yaml" in output
        assert "chapters/01-start.yaml" in output


class TestDisplaySizeWarnings:
    def test_displays_warnings(self):
        warnings = [
            "world.yaml is 200 words (target: under 120).",
            "characters/maya.yaml is 90 words (target: ~60).",
        ]
        output = _capture_console_output(display_size_warnings, warnings)
        assert "world.yaml is 200 words" in output
        assert "characters/maya.yaml is 90 words" in output
        assert "Size Warnings" in output

    def test_displays_single_warning(self):
        warnings = ["chapters/01-start.yaml has 8 beats (target: 4-6)."]
        output = _capture_console_output(display_size_warnings, warnings)
        assert "8 beats" in output

    def test_displays_empty_warnings_list(self):
        output = _capture_console_output(display_size_warnings, [])
        assert "Size Warnings" in output
