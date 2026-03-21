"""Tests for per-file generators (world, character, chapter)."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
import pytest
import yaml
from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import YAMLParseError
from theact.creator.world_gen import generate_world
from theact.creator.character_gen import generate_character
from theact.creator.chapter_gen import generate_chapter


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


def _proposal() -> dict:
    return {
        "title": "Test Game",
        "id": "test-game",
        "setting": "A dark forest.",
        "tone": "Second person, present tense.",
        "rules": "No magic.",
    }


@pytest.mark.asyncio
class TestWorldGenerator:
    async def test_generates_world_data(self):
        world = {
            "setting": "A dark forest at dusk.",
            "tone": "Second person, present tense.",
            "rules": "No magic.",
        }
        response = f"```yaml\n{yaml.dump(world)}```"
        client = _make_mock_client([response])
        result = await generate_world(_proposal(), client, _config())
        assert "setting" in result
        assert "tone" in result
        assert "rules" in result

    async def test_retries_on_parse_failure(self):
        world = {"setting": "Forest.", "tone": "2nd person.", "rules": "None."}
        good_response = f"```yaml\n{yaml.dump(world)}```"
        client = _make_mock_client(["bad yaml {{{", good_response])
        result = await generate_world(_proposal(), client, _config())
        assert "setting" in result

    async def test_raises_after_max_retries(self):
        client = _make_mock_client(["bad yaml {{{", "still bad {{{"])
        with pytest.raises(YAMLParseError):
            await generate_world(_proposal(), client, _config())

    async def test_strips_think_tags(self):
        world = {"setting": "Forest.", "tone": "2nd person.", "rules": "None."}
        yaml_text = yaml.dump(world)
        response = f"<think>reasoning here</think>```yaml\n{yaml_text}```"
        client = _make_mock_client([response])
        result = await generate_world(_proposal(), client, _config())
        assert "setting" in result


@pytest.mark.asyncio
class TestCharacterGenerator:
    async def test_generates_character_data(self):
        char = {
            "name": "Maya",
            "role": "Guide.",
            "personality": "Calm and focused.",
            "secret": "Knows the way out.",
            "relationships": {"jake": "Trusts him."},
        }
        response = f"```yaml\n{yaml.dump(char)}```"
        client = _make_mock_client([response])
        result = await generate_character(
            _proposal(),
            {"stem": "maya", "name": "Maya", "role": "Guide"},
            ["maya", "jake"],
            {},
            client,
            _config(),
        )
        assert result["name"] == "Maya"
        assert "relationships" in result

    async def test_adds_empty_relationships_if_missing(self):
        char = {
            "name": "Solo",
            "role": "Loner.",
            "personality": "Quiet.",
            "secret": "None.",
        }
        response = f"```yaml\n{yaml.dump(char)}```"
        client = _make_mock_client([response])
        result = await generate_character(
            _proposal(),
            {"stem": "solo", "name": "Solo", "role": "Loner"},
            ["solo"],
            {},
            client,
            _config(),
        )
        assert result["relationships"] == {}


@pytest.mark.asyncio
class TestChapterGenerator:
    async def test_generates_chapter_data(self):
        chap = {
            "id": "01-start",
            "title": "The Start",
            "summary": "Begin.",
            "beats": ["Enter", "Walk", "Find", "Done"],
            "completion": "Player done.",
            "characters": ["maya"],
            "next": "02-end",
        }
        response = f"```yaml\n{yaml.dump(chap)}```"
        client = _make_mock_client([response])
        result = await generate_chapter(
            _proposal(),
            {"id": "01-start", "title": "The Start", "summary": "Begin."},
            {"maya": {"name": "Maya"}},
            {},
            "02-end",
            client,
            _config(),
        )
        assert result["id"] == "01-start"
        assert result["next"] == "02-end"  # Code-enforced

    async def test_code_enforces_next_pointer(self):
        """Even if model returns wrong next, code overrides it."""
        chap = {
            "id": "01-x",
            "title": "X",
            "summary": "X.",
            "beats": ["a", "b", "c", "d"],
            "completion": "Done.",
            "characters": [],
            "next": "wrong-value",
        }
        response = f"```yaml\n{yaml.dump(chap)}```"
        client = _make_mock_client([response])
        result = await generate_chapter(
            _proposal(),
            {"id": "01-x", "title": "X", "summary": "X."},
            {},
            {},
            None,  # This is the last chapter
            client,
            _config(),
        )
        assert result["next"] is None  # Code enforced
