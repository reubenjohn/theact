"""Tests for the decomposed generation pipeline."""

from __future__ import annotations

import pytest
import yaml

from tests.conftest import creator_config, make_mock_client
from theact.creator.pipeline import run_generation_pipeline


def _sample_proposal() -> dict:
    return {
        "title": "Test Game",
        "id": "test-game",
        "setting": "A dark forest.",
        "tone": "Second person, present tense.",
        "rules": "No magic.",
        "characters": [
            {"stem": "maya", "name": "Maya", "role": "Guide"},
        ],
        "chapters": [
            {"id": "01-start", "title": "The Start", "summary": "Begin."},
        ],
    }


WORLD_RESPONSE = yaml.dump(
    {
        "setting": "A dark forest at dusk.",
        "tone": "Second person, present tense. 100-250 words.",
        "rules": "No magic. No breaking the fourth wall.",
    },
    default_flow_style=False,
)

CHARACTER_RESPONSE = yaml.dump(
    {
        "name": "Maya",
        "role": "Guide through the forest.",
        "personality": "Calm and focused. Speaks in short, direct sentences.",
        "secret": "She knows the way out.",
        "relationships": {},
    },
    default_flow_style=False,
)

CHAPTER_RESPONSE = yaml.dump(
    {
        "id": "01-start",
        "title": "The Start",
        "summary": "The player enters the dark forest.",
        "beats": ["Enter the forest", "Meet Maya", "Find the path", "Reach clearing"],
        "completion": "Player has reached the clearing.",
        "characters": ["maya"],
        "next": None,
    },
    default_flow_style=False,
)


@pytest.mark.asyncio
class TestRunGenerationPipeline:
    async def test_produces_complete_game_data(self):
        client = make_mock_client(
            [
                f"```yaml\n{WORLD_RESPONSE}```",
                f"```yaml\n{CHARACTER_RESPONSE}```",
                f"```yaml\n{CHAPTER_RESPONSE}```",
            ]
        )
        result = await run_generation_pipeline(
            _sample_proposal(), client, creator_config()
        )
        assert "game" in result
        assert "world" in result
        assert "characters" in result
        assert "chapters" in result
        assert result["game"]["id"] == "test-game"
        assert "maya" in result["characters"]
        assert "01-start" in result["chapters"]

    async def test_progress_callback_invoked(self):
        client = make_mock_client(
            [
                f"```yaml\n{WORLD_RESPONSE}```",
                f"```yaml\n{CHARACTER_RESPONSE}```",
                f"```yaml\n{CHAPTER_RESPONSE}```",
            ]
        )
        progress_messages = []
        await run_generation_pipeline(
            _sample_proposal(),
            client,
            creator_config(),
            on_progress=lambda msg: progress_messages.append(msg),
        )
        assert any("world" in m.lower() for m in progress_messages)
        assert any("maya" in m.lower() for m in progress_messages)
        assert any("start" in m.lower() for m in progress_messages)

    async def test_raises_on_empty_characters(self):
        proposal = _sample_proposal()
        proposal["characters"] = []
        client = make_mock_client([])
        with pytest.raises(ValueError, match="no characters"):
            await run_generation_pipeline(proposal, client, creator_config())

    async def test_enforces_consistency(self):
        """Pipeline runs enforce_consistency after assembly."""
        # World + character + chapter with a self-referencing relationship
        char_with_self = yaml.dump(
            {
                "name": "Maya",
                "role": "Guide.",
                "personality": "Calm.",
                "secret": "Knows the way.",
                "relationships": {"maya": "self-reference"},
            },
            default_flow_style=False,
        )

        client = make_mock_client(
            [
                f"```yaml\n{WORLD_RESPONSE}```",
                f"```yaml\n{char_with_self}```",
                f"```yaml\n{CHAPTER_RESPONSE}```",
            ]
        )
        result = await run_generation_pipeline(
            _sample_proposal(), client, creator_config()
        )
        # Self-reference should be removed by enforce_consistency
        assert "maya" not in result["characters"]["maya"]["relationships"]
