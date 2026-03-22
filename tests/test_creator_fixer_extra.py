"""Extra tests for creator fixer covering character/chapter file branches
and game.yaml error skipping.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from theact.creator.config import CreatorLLMConfig
from theact.creator.fixer import (
    _group_errors_by_file,
    _parse_file_key,
    _update_data,
    fix_file,
    fix_validation_errors,
)
from theact.creator.validator import ValidationError, validate_game_data


def _make_mock_client(responses: list[str]) -> AsyncMock:
    """Create a mock AsyncOpenAI client that returns canned responses."""
    client = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        idx = min(call_count, len(responses) - 1)
        call_count += 1
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = responses[idx]
        return mock_response

    client.chat.completions.create = fake_create
    return client


def _config() -> CreatorLLMConfig:
    return CreatorLLMConfig(api_key="test-key", model="test-model")


def _valid_game_data() -> dict:
    return {
        "game": {
            "id": "test-game",
            "title": "Test Game",
            "description": "A test game.",
            "characters": ["maya"],
            "chapters": ["01-start"],
        },
        "world": {
            "setting": "A dark forest.",
            "tone": "Second person, present tense.",
            "rules": "No magic.",
        },
        "characters": {
            "maya": {
                "name": "Maya",
                "role": "Guide.",
                "personality": "Calm.",
                "secret": "Knows the way.",
                "relationships": {},
            },
        },
        "chapters": {
            "01-start": {
                "id": "01-start",
                "title": "The Start",
                "summary": "Begin.",
                "beats": ["Enter", "Walk", "Find", "Leave"],
                "completion": "Done.",
                "characters": ["maya"],
                "next": None,
            },
        },
    }


class TestParseFileKey:
    def test_world_yaml(self):
        file_type, stem = _parse_file_key("world.yaml")
        assert file_type == "world"
        assert stem == "world"

    def test_game_yaml(self):
        file_type, stem = _parse_file_key("game.yaml")
        assert file_type == "game"
        assert stem == "game"

    def test_character_file(self):
        file_type, stem = _parse_file_key("characters/maya.yaml")
        assert file_type == "characters"
        assert stem == "maya"

    def test_chapter_file(self):
        file_type, stem = _parse_file_key("chapters/01-start.yaml")
        assert file_type == "chapters"
        assert stem == "01-start"

    def test_unknown_file(self):
        file_type, stem = _parse_file_key("something-else.yaml")
        assert file_type == "unknown"
        assert stem == "something-else.yaml"


class TestUpdateData:
    def test_update_world(self):
        data = {"world": {"setting": "Old."}}
        _update_data(data, "world", "world", {"setting": "New."})
        assert data["world"]["setting"] == "New."

    def test_update_character(self):
        data = {"characters": {"maya": {"name": "Maya", "role": "Old."}}}
        _update_data(data, "characters", "maya", {"name": "Maya", "role": "New."})
        assert data["characters"]["maya"]["role"] == "New."

    def test_update_chapter(self):
        data = {"chapters": {"01-start": {"title": "Old."}}}
        _update_data(data, "chapters", "01-start", {"title": "New."})
        assert data["chapters"]["01-start"]["title"] == "New."

    def test_update_unknown_type_is_noop(self):
        data = {"world": {"setting": "Original."}}
        _update_data(data, "unknown", "x", {"setting": "Changed."})
        assert data["world"]["setting"] == "Original."


class TestGroupErrorsByFile:
    def test_groups_errors_correctly(self):
        errors = [
            ValidationError("world.yaml", "setting", "Missing setting"),
            ValidationError("world.yaml", "tone", "Missing tone"),
            ValidationError("characters/maya.yaml", "", "Invalid character"),
            ValidationError("chapters/01-start.yaml", "beats", "Too few beats"),
        ]
        groups = _group_errors_by_file(errors)
        assert len(groups["world.yaml"]) == 2
        assert len(groups["characters/maya.yaml"]) == 1
        assert len(groups["chapters/01-start.yaml"]) == 1


@pytest.mark.asyncio
class TestFixFileFunction:
    async def test_fix_file_returns_fixed_data(self):
        fixed = {"setting": "New setting.", "tone": "2nd person.", "rules": "None."}
        response = f"```yaml\n{yaml.dump(fixed)}```"
        client = _make_mock_client([response])
        errors = [ValidationError("world.yaml", "setting", "Missing setting")]
        result = await fix_file(
            "world",
            "world",
            {"tone": "2nd person.", "rules": "None."},
            errors,
            {"title": "Test"},
            client,
            _config(),
        )
        assert result["setting"] == "New setting."

    async def test_fix_file_returns_original_on_parse_failure(self):
        """When the LLM returns unparseable YAML, the original data is returned."""
        client = _make_mock_client(["not valid yaml at all"])
        original = {"tone": "2nd person.", "rules": "None."}
        errors = [ValidationError("world.yaml", "setting", "Missing setting")]
        result = await fix_file(
            "world", "world", original, errors, {"title": "Test"}, client, _config()
        )
        assert result == original


@pytest.mark.asyncio
class TestFixCharacterErrors:
    async def test_fixes_broken_character(self):
        """Fix a character with missing personality field."""
        data = _valid_game_data()
        # Remove personality to trigger validation error
        del data["characters"]["maya"]["personality"]
        result = validate_game_data(data)
        assert not result.valid

        fixed_char = {
            "name": "Maya",
            "role": "Guide.",
            "personality": "Calm and focused.",
            "secret": "Knows the way.",
            "relationships": {},
        }
        fixed_yaml = yaml.dump(fixed_char, default_flow_style=False, sort_keys=False)
        response = f"```yaml\n{fixed_yaml}```"

        client = _make_mock_client([response])
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, _config()
        )
        assert fixed_result.valid


@pytest.mark.asyncio
class TestFixChapterErrors:
    async def test_fixes_broken_chapter(self):
        """Fix a chapter with missing beats field."""
        data = _valid_game_data()
        # Remove beats to trigger validation error
        del data["chapters"]["01-start"]["beats"]
        result = validate_game_data(data)
        assert not result.valid

        fixed_chap = {
            "id": "01-start",
            "title": "The Start",
            "summary": "Begin.",
            "beats": ["Enter", "Walk", "Find", "Leave"],
            "completion": "Done.",
            "characters": ["maya"],
            "next": None,
        }
        fixed_yaml = yaml.dump(fixed_chap, default_flow_style=False, sort_keys=False)
        response = f"```yaml\n{fixed_yaml}```"

        client = _make_mock_client([response])
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, _config()
        )
        assert fixed_result.valid


@pytest.mark.asyncio
class TestFixGameYamlErrorsSkipped:
    async def test_game_yaml_errors_skipped_and_reassembled(self):
        """Errors on game.yaml are not sent to the LLM -- game.yaml is reassembled."""
        data = _valid_game_data()
        # Corrupt game.yaml to trigger a game.yaml-specific error
        data["game"]["characters"] = ["nonexistent"]

        result = validate_game_data(data)
        assert not result.valid

        # The fixer should NOT call the LLM for game.yaml errors.
        # It should reassemble game.yaml from the actual characters/chapters.
        client = _make_mock_client(["should not be called"])
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, _config()
        )
        # After reassembly, game.yaml should list "maya" (from actual characters)
        assert "maya" in fixed_data["game"]["characters"]
        assert fixed_result.valid
