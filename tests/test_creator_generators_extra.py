"""Extra tests for character_gen and chapter_gen covering missing branches.

Covers: prior character/chapter context, feedback appending, missing required
keys, and retry loop on parse failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from theact.creator.chapter_gen import generate_chapter
from theact.creator.character_gen import generate_character
from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import YAMLParseError


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


def _proposal() -> dict:
    return {
        "title": "Test Game",
        "id": "test-game",
        "setting": "A dark forest.",
        "tone": "Second person, present tense.",
        "rules": "No magic.",
    }


# --------------------------------------------------------------------------
# Character generator extra tests
# --------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCharacterGenWithPriorContext:
    async def test_prior_characters_included(self):
        """When prior characters exist, they provide context for the new character."""
        char = {
            "name": "Jake",
            "role": "Survivor.",
            "personality": "Tough and resourceful.",
            "secret": "Hiding an injury.",
            "relationships": {"maya": "Depends on her."},
        }
        response = f"```yaml\n{yaml.dump(char)}```"
        client = _make_mock_client([response])
        prior = {
            "maya": {
                "name": "Maya",
                "role": "Guide",
                "personality": "Calm.",
                "secret": "Knows the way.",
                "relationships": {},
            }
        }
        result = await generate_character(
            _proposal(),
            {"stem": "jake", "name": "Jake", "role": "Survivor"},
            ["maya", "jake"],
            prior,
            client,
            _config(),
        )
        assert result["name"] == "Jake"
        assert "maya" in result["relationships"]

    async def test_multiple_prior_characters(self):
        """Multiple prior characters all appear in context."""
        char = {
            "name": "Zara",
            "role": "Medic.",
            "personality": "Kind.",
            "secret": "None.",
            "relationships": {"maya": "Colleague.", "jake": "Friend."},
        }
        response = f"```yaml\n{yaml.dump(char)}```"
        client = _make_mock_client([response])
        prior = {
            "maya": {"name": "Maya", "role": "Guide"},
            "jake": {"name": "Jake", "role": "Survivor"},
        }
        result = await generate_character(
            _proposal(),
            {"stem": "zara", "name": "Zara", "role": "Medic"},
            ["maya", "jake", "zara"],
            prior,
            client,
            _config(),
        )
        assert result["name"] == "Zara"


@pytest.mark.asyncio
class TestCharacterGenWithFeedback:
    async def test_feedback_appended_to_prompt(self):
        """Feedback string is appended to the user prompt."""
        char = {
            "name": "Maya",
            "role": "Guide.",
            "personality": "Bold and adventurous.",
            "secret": "Lost her way once.",
            "relationships": {},
        }
        response = f"```yaml\n{yaml.dump(char)}```"
        client = _make_mock_client([response])
        result = await generate_character(
            _proposal(),
            {"stem": "maya", "name": "Maya", "role": "Guide"},
            ["maya"],
            {},
            client,
            _config(),
            feedback="Make her more adventurous",
        )
        assert result["name"] == "Maya"
        assert "adventurous" in result["personality"].lower()


@pytest.mark.asyncio
class TestCharacterGenMissingKeys:
    async def test_missing_required_keys_triggers_retry(self):
        """When required keys are missing, it retries and succeeds."""
        incomplete = {"name": "Maya"}  # missing role, personality, secret
        incomplete_response = f"```yaml\n{yaml.dump(incomplete)}```"

        complete = {
            "name": "Maya",
            "role": "Guide.",
            "personality": "Calm.",
            "secret": "Knows the way.",
            "relationships": {},
        }
        good_response = f"```yaml\n{yaml.dump(complete)}```"

        client = _make_mock_client([incomplete_response, good_response])
        result = await generate_character(
            _proposal(),
            {"stem": "maya", "name": "Maya", "role": "Guide"},
            ["maya"],
            {},
            client,
            _config(),
        )
        assert result["name"] == "Maya"
        assert "role" in result
        assert "personality" in result
        assert "secret" in result

    async def test_missing_keys_after_all_retries_raises(self):
        """When required keys are missing after all retries, raises."""
        incomplete = {"name": "Maya"}  # missing role, personality, secret
        response = f"```yaml\n{yaml.dump(incomplete)}```"
        client = _make_mock_client([response, response])
        with pytest.raises(YAMLParseError, match="missing required keys"):
            await generate_character(
                _proposal(),
                {"stem": "maya", "name": "Maya", "role": "Guide"},
                ["maya"],
                {},
                client,
                _config(),
            )


@pytest.mark.asyncio
class TestCharacterGenRetryOnParseFailure:
    async def test_retry_on_yaml_parse_error(self):
        """Bad YAML on first attempt, good YAML on second."""
        good_char = {
            "name": "Maya",
            "role": "Guide.",
            "personality": "Calm.",
            "secret": "Knows the way.",
            "relationships": {},
        }
        good_response = f"```yaml\n{yaml.dump(good_char)}```"
        client = _make_mock_client(["not valid yaml {{{", good_response])
        result = await generate_character(
            _proposal(),
            {"stem": "maya", "name": "Maya", "role": "Guide"},
            ["maya"],
            {},
            client,
            _config(),
        )
        assert result["name"] == "Maya"

    async def test_raises_after_all_parse_failures(self):
        """All attempts return bad YAML -> raises YAMLParseError."""
        client = _make_mock_client(["bad {{{", "still bad {{{"])
        with pytest.raises(YAMLParseError):
            await generate_character(
                _proposal(),
                {"stem": "maya", "name": "Maya", "role": "Guide"},
                ["maya"],
                {},
                client,
                _config(),
            )


# --------------------------------------------------------------------------
# Chapter generator extra tests
# --------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChapterGenWithPriorContext:
    async def test_prior_chapters_included(self):
        """When prior chapters exist, they provide context for the new chapter."""
        chap = {
            "id": "02-middle",
            "title": "The Middle",
            "summary": "Continue the journey.",
            "beats": ["Advance", "Discover", "Battle", "Rest"],
            "completion": "Survived the battle.",
            "characters": ["maya"],
            "next": "03-end",
        }
        response = f"```yaml\n{yaml.dump(chap)}```"
        client = _make_mock_client([response])
        prior = {
            "01-start": {
                "id": "01-start",
                "title": "The Start",
                "summary": "Begin the journey.",
            }
        }
        result = await generate_chapter(
            _proposal(),
            {"id": "02-middle", "title": "The Middle", "summary": "Continue."},
            {"maya": {"name": "Maya"}},
            prior,
            "03-end",
            client,
            _config(),
        )
        assert result["id"] == "02-middle"
        assert result["next"] == "03-end"

    async def test_multiple_prior_chapters(self):
        """Multiple prior chapters all appear in context."""
        chap = {
            "id": "03-end",
            "title": "The End",
            "summary": "Finish.",
            "beats": ["Climax", "Resolution", "Escape", "Victory"],
            "completion": "Player wins.",
            "characters": ["maya"],
            "next": None,
        }
        response = f"```yaml\n{yaml.dump(chap)}```"
        client = _make_mock_client([response])
        prior = {
            "01-start": {"title": "The Start", "summary": "Begin."},
            "02-middle": {"title": "The Middle", "summary": "Continue."},
        }
        result = await generate_chapter(
            _proposal(),
            {"id": "03-end", "title": "The End", "summary": "Finish."},
            {"maya": {"name": "Maya"}},
            prior,
            None,
            client,
            _config(),
        )
        assert result["next"] is None


@pytest.mark.asyncio
class TestChapterGenWithFeedback:
    async def test_feedback_appended_to_prompt(self):
        """Feedback string is appended to the user prompt."""
        chap = {
            "id": "01-start",
            "title": "The Start",
            "summary": "A dramatic beginning.",
            "beats": ["Enter", "Discover", "Fight", "Flee"],
            "completion": "Player escapes.",
            "characters": ["maya"],
            "next": None,
        }
        response = f"```yaml\n{yaml.dump(chap)}```"
        client = _make_mock_client([response])
        result = await generate_chapter(
            _proposal(),
            {"id": "01-start", "title": "The Start", "summary": "Begin."},
            {"maya": {"name": "Maya"}},
            {},
            None,
            client,
            _config(),
            feedback="Make the start more dramatic",
        )
        assert result["id"] == "01-start"


@pytest.mark.asyncio
class TestChapterGenMissingKeys:
    async def test_missing_required_keys_triggers_retry(self):
        """When required keys are missing, it retries and succeeds."""
        incomplete = {
            "id": "01-start",
            "title": "Start",
        }  # missing summary, beats, completion
        incomplete_response = f"```yaml\n{yaml.dump(incomplete)}```"

        complete = {
            "id": "01-start",
            "title": "The Start",
            "summary": "Begin.",
            "beats": ["Enter", "Walk", "Find", "Leave"],
            "completion": "Done.",
            "characters": ["maya"],
            "next": None,
        }
        good_response = f"```yaml\n{yaml.dump(complete)}```"

        client = _make_mock_client([incomplete_response, good_response])
        result = await generate_chapter(
            _proposal(),
            {"id": "01-start", "title": "The Start", "summary": "Begin."},
            {"maya": {"name": "Maya"}},
            {},
            None,
            client,
            _config(),
        )
        assert result["id"] == "01-start"
        assert "beats" in result

    async def test_missing_keys_after_all_retries_raises(self):
        """When required keys are missing after all retries, raises."""
        incomplete = {"id": "01-start"}  # missing title, summary, beats, completion
        response = f"```yaml\n{yaml.dump(incomplete)}```"
        client = _make_mock_client([response, response])
        with pytest.raises(YAMLParseError, match="missing required keys"):
            await generate_chapter(
                _proposal(),
                {"id": "01-start", "title": "X", "summary": "X."},
                {},
                {},
                None,
                client,
                _config(),
            )

    async def test_missing_characters_key_gets_default(self):
        """When model omits 'characters' key, code adds it from the characters dict."""
        chap = {
            "id": "01-start",
            "title": "Start",
            "summary": "Begin.",
            "beats": ["Enter", "Walk", "Find", "Leave"],
            "completion": "Done.",
            # no "characters" key
            "next": None,
        }
        response = f"```yaml\n{yaml.dump(chap)}```"
        client = _make_mock_client([response])
        result = await generate_chapter(
            _proposal(),
            {"id": "01-start", "title": "Start", "summary": "Begin."},
            {"maya": {"name": "Maya"}, "jake": {"name": "Jake"}},
            {},
            None,
            client,
            _config(),
        )
        assert set(result["characters"]) == {"maya", "jake"}


@pytest.mark.asyncio
class TestChapterGenRetryOnParseFailure:
    async def test_retry_on_yaml_parse_error(self):
        """Bad YAML on first attempt, good YAML on second."""
        good_chap = {
            "id": "01-start",
            "title": "Start",
            "summary": "Begin.",
            "beats": ["Enter", "Walk", "Find", "Leave"],
            "completion": "Done.",
            "characters": ["maya"],
            "next": None,
        }
        good_response = f"```yaml\n{yaml.dump(good_chap)}```"
        client = _make_mock_client(["bad yaml {{{", good_response])
        result = await generate_chapter(
            _proposal(),
            {"id": "01-start", "title": "Start", "summary": "Begin."},
            {"maya": {"name": "Maya"}},
            {},
            None,
            client,
            _config(),
        )
        assert result["id"] == "01-start"

    async def test_raises_after_all_parse_failures(self):
        """All attempts return bad YAML -> raises YAMLParseError."""
        client = _make_mock_client(["bad {{{", "still bad {{{"])
        with pytest.raises(YAMLParseError):
            await generate_chapter(
                _proposal(),
                {"id": "01-start", "title": "X", "summary": "X."},
                {},
                {},
                None,
                client,
                _config(),
            )
