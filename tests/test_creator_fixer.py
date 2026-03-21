"""Tests for creator fixer (validation error fix loop)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from theact.creator.config import CreatorLLMConfig
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


@pytest.mark.asyncio
class TestFixValidationErrors:
    async def test_already_valid_no_llm_calls(self):
        data = _valid_game_data()
        result = validate_game_data(data)
        assert result.valid

        client = _make_mock_client(["should not be called"])
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, _config()
        )
        assert fixed_result.valid

    async def test_fixes_on_first_attempt(self):
        # Start with broken data (missing world.setting)
        data = _valid_game_data()
        del data["world"]["setting"]
        result = validate_game_data(data)
        assert not result.valid

        # The LLM returns a fixed version
        fixed = _valid_game_data()
        fixed_yaml = yaml.dump(fixed, default_flow_style=False, sort_keys=False)
        response = f"```yaml\n{fixed_yaml}```"

        client = _make_mock_client([response])
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, _config()
        )
        assert fixed_result.valid

    async def test_gives_up_after_max_attempts(self):
        # Start with broken data
        data = _valid_game_data()
        del data["world"]["setting"]
        result = validate_game_data(data)
        assert not result.valid

        # The LLM always returns the same broken data
        broken_yaml = yaml.dump(data, default_flow_style=False, sort_keys=False)
        response = f"```yaml\n{broken_yaml}```"

        client = _make_mock_client([response] * MAX_FIX_ATTEMPTS)
        _fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, _config()
        )
        assert not fixed_result.valid

    async def test_handles_yaml_parse_error(self):
        data = _valid_game_data()
        del data["world"]["setting"]
        result = validate_game_data(data)
        assert not result.valid

        # LLM returns garbage YAML, then valid YAML
        fixed = _valid_game_data()
        fixed_yaml = yaml.dump(fixed, default_flow_style=False, sort_keys=False)

        client = _make_mock_client(
            [
                "not valid yaml {{{",
                f"```yaml\n{fixed_yaml}```",
            ]
        )
        fixed_data, fixed_result = await fix_validation_errors(
            data, result, client, _config()
        )
        assert fixed_result.valid
