"""Tests for creator fixer (per-file validation error fix loop)."""

from __future__ import annotations

import pytest
import yaml

from tests.conftest import creator_config, make_mock_client
from theact.creator.fixer import MAX_FIX_ATTEMPTS, fix_validation_errors
from theact.creator.validator import validate_game_data


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


@pytest.mark.asyncio
class TestFixValidationErrors:
    async def test_already_valid_no_llm_calls(self):
        data = _valid_game_data()
        result = validate_game_data(data)
        assert result.valid

        client = make_mock_client(["should not be called"])
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, creator_config()
        )
        assert fixed_result.valid

    async def test_fixes_on_first_attempt(self):
        # Start with broken data (missing world.setting)
        data = _valid_game_data()
        del data["world"]["setting"]
        result = validate_game_data(data)
        assert not result.valid

        # The per-file fixer sends only the world data and expects
        # the fixed world data back (not the entire game)
        fixed_world = {
            "setting": "A dark forest.",
            "tone": "Second person, present tense.",
            "rules": "No magic.",
        }
        fixed_yaml = yaml.dump(fixed_world, default_flow_style=False, sort_keys=False)
        response = f"```yaml\n{fixed_yaml}```"

        client = make_mock_client([response])
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, creator_config()
        )
        assert fixed_result.valid

    async def test_gives_up_after_max_attempts(self):
        # Start with broken data
        data = _valid_game_data()
        del data["world"]["setting"]
        result = validate_game_data(data)
        assert not result.valid

        # The LLM always returns the same broken world data (missing setting)
        broken_world = {"tone": "Second person.", "rules": "No magic."}
        broken_yaml = yaml.dump(broken_world, default_flow_style=False, sort_keys=False)
        response = f"```yaml\n{broken_yaml}```"

        client = make_mock_client([response] * MAX_FIX_ATTEMPTS)
        _fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, creator_config()
        )
        assert not fixed_result.valid

    async def test_handles_yaml_parse_error(self):
        data = _valid_game_data()
        del data["world"]["setting"]
        result = validate_game_data(data)
        assert not result.valid

        # LLM returns garbage YAML, then valid per-file YAML
        fixed_world = {
            "setting": "A dark forest.",
            "tone": "Second person, present tense.",
            "rules": "No magic.",
        }
        fixed_yaml = yaml.dump(fixed_world, default_flow_style=False, sort_keys=False)

        client = make_mock_client(
            [
                "not valid yaml {{{",
                f"```yaml\n{fixed_yaml}```",
            ]
        )
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, creator_config()
        )
        assert fixed_result.valid
