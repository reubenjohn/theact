"""Tests for proposer revision functions and legacy monolithic proposal flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import YAMLParseError
from theact.creator.proposer import (
    generate_proposal,
    revise_chapters_proposal,
    revise_characters_proposal,
    revise_proposal,
    revise_setting,
)


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
class TestReviseSetting:
    async def test_revise_setting_happy_path(self):
        revised = {
            "title": "Haunted Forest",
            "id": "haunted-forest",
            "setting": "A haunted forest at midnight.",
            "tone": "Third person, past tense.",
            "rules": "Ghosts exist.",
        }
        response = f"```yaml\n{yaml.dump(revised)}```"
        client = _make_mock_client([response])

        current = {
            "title": "Dark Forest",
            "id": "dark-forest",
            "setting": "A dark forest.",
            "tone": "Second person.",
            "rules": "No magic.",
        }
        result = await revise_setting(current, "Make it haunted", client, _config())
        assert result["title"] == "Haunted Forest"
        assert "haunted" in result["setting"].lower()

    async def test_revise_setting_with_feedback(self):
        revised = {
            "title": "Bright Forest",
            "id": "bright-forest",
            "setting": "A bright sunny forest.",
            "tone": "First person.",
            "rules": "Nature is friendly.",
        }
        response = f"```yaml\n{yaml.dump(revised)}```"
        client = _make_mock_client([response])

        current = {"title": "Dark Forest", "id": "dark-forest"}
        result = await revise_setting(
            current, "Make it bright and sunny", client, _config()
        )
        assert result["title"] == "Bright Forest"


@pytest.mark.asyncio
class TestReviseCharactersProposal:
    async def test_revise_characters_happy_path(self):
        revised = {
            "characters": [
                {"stem": "elena", "name": "Elena", "role": "Warrior"},
                {"stem": "kai", "name": "Kai", "role": "Healer"},
            ]
        }
        response = f"```yaml\n{yaml.dump(revised)}```"
        client = _make_mock_client([response])

        current = {
            "characters": [
                {"stem": "maya", "name": "Maya", "role": "Guide"},
            ]
        }
        setting = {"title": "Forest", "setting": "Dark woods.", "tone": "Grim."}
        result = await revise_characters_proposal(
            current,
            setting,
            "Replace Maya with a warrior and healer",
            client,
            _config(),
        )
        assert len(result["characters"]) == 2
        assert result["characters"][0]["name"] == "Elena"

    async def test_revise_characters_preserves_setting_context(self):
        revised = {
            "characters": [
                {"stem": "maya", "name": "Maya", "role": "Updated Guide"},
            ]
        }
        response = f"```yaml\n{yaml.dump(revised)}```"
        client = _make_mock_client([response])

        current = {"characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}]}
        setting = {"title": "Forest", "setting": "Dark woods."}
        result = await revise_characters_proposal(
            current, setting, "Update Maya's role", client, _config()
        )
        assert result["characters"][0]["role"] == "Updated Guide"


@pytest.mark.asyncio
class TestReviseChaptersProposal:
    async def test_revise_chapters_happy_path(self):
        revised = {
            "chapters": [
                {"id": "01-dawn", "title": "Dawn", "summary": "A new beginning."},
                {"id": "02-dusk", "title": "Dusk", "summary": "The end comes."},
            ]
        }
        response = f"```yaml\n{yaml.dump(revised)}```"
        client = _make_mock_client([response])

        current = {
            "chapters": [{"id": "01-start", "title": "Start", "summary": "Begin."}]
        }
        setting = {"title": "Forest", "setting": "Dark woods."}
        characters = {"characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}]}
        result = await revise_chapters_proposal(
            current, setting, characters, "Split into dawn and dusk", client, _config()
        )
        assert len(result["chapters"]) == 2
        assert result["chapters"][0]["id"] == "01-dawn"

    async def test_revise_chapters_with_no_characters(self):
        revised = {
            "chapters": [{"id": "01-solo", "title": "Solo", "summary": "Alone."}]
        }
        response = f"```yaml\n{yaml.dump(revised)}```"
        client = _make_mock_client([response])

        current = {"chapters": [{"id": "01-x", "title": "X", "summary": "X."}]}
        setting = {"title": "Test", "setting": "Test."}
        characters = {"characters": []}
        result = await revise_chapters_proposal(
            current, setting, characters, "Make it solo", client, _config()
        )
        assert result["chapters"][0]["title"] == "Solo"


@pytest.mark.asyncio
class TestLegacyGenerateProposal:
    async def test_generate_proposal_happy_path(self):
        proposal = {
            "title": "Dark Forest",
            "id": "dark-forest",
            "setting": "A dark forest.",
            "tone": "Second person.",
            "rules": "No magic.",
            "characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}],
            "chapters": [{"id": "01-start", "title": "Start", "summary": "Begin."}],
        }
        response = f"```yaml\n{yaml.dump(proposal)}```"
        client = _make_mock_client([response])
        result = await generate_proposal("A dark forest game", client, _config())
        assert result["title"] == "Dark Forest"
        assert "characters" in result
        assert "chapters" in result

    async def test_generate_proposal_raises_on_bad_yaml(self):
        client = _make_mock_client(["not valid yaml {{{"])
        with pytest.raises(YAMLParseError):
            await generate_proposal("test concept", client, _config())


@pytest.mark.asyncio
class TestLegacyReviseProposal:
    async def test_revise_proposal_happy_path(self):
        revised = {
            "title": "Haunted Forest",
            "id": "haunted-forest",
            "setting": "A haunted forest.",
            "tone": "Third person.",
            "rules": "Ghosts exist.",
            "characters": [{"stem": "ghost", "name": "Ghost", "role": "Spirit"}],
            "chapters": [{"id": "01-haunt", "title": "Haunt", "summary": "Spooky."}],
        }
        response = f"```yaml\n{yaml.dump(revised)}```"
        client = _make_mock_client([response])

        current = {
            "title": "Dark Forest",
            "id": "dark-forest",
            "setting": "A dark forest.",
            "characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}],
            "chapters": [{"id": "01-start", "title": "Start", "summary": "Begin."}],
        }
        result = await revise_proposal(current, "Make it haunted", client, _config())
        assert result["title"] == "Haunted Forest"
        assert result["characters"][0]["name"] == "Ghost"

    async def test_revise_proposal_raises_on_bad_yaml(self):
        client = _make_mock_client(["garbage response"])
        current = {
            "title": "Test",
            "id": "test",
            "characters": [],
            "chapters": [],
        }
        with pytest.raises(YAMLParseError):
            await revise_proposal(current, "change everything", client, _config())
