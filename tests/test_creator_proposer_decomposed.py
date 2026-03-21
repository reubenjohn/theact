"""Tests for decomposed proposal generation."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
import pytest
import yaml
from theact.creator.config import CreatorLLMConfig
from theact.creator.proposer import (
    assemble_proposal,
    generate_setting,
    generate_characters_proposal,
    generate_chapters_proposal,
)


def _make_mock_client(responses: list[str]) -> AsyncMock:
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
class TestGenerateSetting:
    async def test_produces_setting_data(self):
        setting = {
            "title": "Dark Forest",
            "id": "dark-forest",
            "setting": "A dark forest at dusk.",
            "tone": "Second person, present tense.",
            "rules": "No magic.",
        }
        response = f"```yaml\n{yaml.dump(setting)}```"
        client = _make_mock_client([response])
        result = await generate_setting("A dark forest game", client, _config())
        assert result["title"] == "Dark Forest"
        assert result["id"] == "dark-forest"


@pytest.mark.asyncio
class TestGenerateCharactersProposal:
    async def test_produces_characters_data(self):
        chars = {
            "characters": [
                {"stem": "maya", "name": "Maya", "role": "Guide"},
            ]
        }
        response = f"```yaml\n{yaml.dump(chars)}```"
        setting = {"title": "Test", "setting": "Forest.", "tone": "2p."}
        client = _make_mock_client([response])
        result = await generate_characters_proposal(setting, client, _config())
        assert "characters" in result
        assert len(result["characters"]) == 1


@pytest.mark.asyncio
class TestGenerateChaptersProposal:
    async def test_produces_chapters_data(self):
        chaps = {
            "chapters": [
                {"id": "01-start", "title": "Start", "summary": "Begin."},
            ]
        }
        response = f"```yaml\n{yaml.dump(chaps)}```"
        setting = {"title": "Test", "setting": "Forest."}
        chars = {"characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}]}
        client = _make_mock_client([response])
        result = await generate_chapters_proposal(setting, chars, client, _config())
        assert "chapters" in result


class TestAssembleProposal:
    def test_assembles_complete_proposal(self):
        setting = {"title": "T", "id": "t", "setting": "S", "tone": "T", "rules": "R"}
        characters = {"characters": [{"stem": "m", "name": "M", "role": "R"}]}
        chapters = {"chapters": [{"id": "01-x", "title": "X", "summary": "S"}]}
        result = assemble_proposal(setting, characters, chapters)
        assert result["title"] == "T"
        assert result["id"] == "t"
        assert result["setting"] == "S"
        assert len(result["characters"]) == 1
        assert len(result["chapters"]) == 1
