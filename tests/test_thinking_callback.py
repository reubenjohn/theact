"""Tests that thinking tokens flow through agent callbacks.

Verifies that the narrator and character agents forward thinking tokens
to their on_token callback with is_thinking=True, and content tokens
with is_thinking=False.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from theact.engine.types import CharacterResponse, NarratorOutput
from theact.llm.config import LLMConfig
from theact.llm.streaming import StreamChunk, StructuredResult
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.game import GameMeta, LoadedGame
from theact.models.state import GameState
from theact.models.world import World


# --- Helpers ---


def _make_game(tmp_path: Path, characters: dict | None = None) -> LoadedGame:
    save_path = tmp_path / "saves" / "test"
    save_path.mkdir(parents=True, exist_ok=True)
    char = Character(
        name="Maya",
        role="Guide",
        personality="Calm",
        secret="None",
        relationships={},
    )
    return LoadedGame(
        meta=GameMeta(
            id="test",
            title="Test",
            description="t",
            characters=["maya"],
            chapters=["ch1"],
        ),
        world=World(setting="Island", tone="Tense", rules="None"),
        characters=characters or {"maya": char},
        chapters={
            "ch1": Chapter(
                id="ch1",
                title="Ch1",
                summary="s",
                beats=["a"],
                completion="done",
                characters=[],
                next=None,
            )
        },
        state=GameState(
            player_name="Alex",
            current_chapter="ch1",
            turn=1,
            beats_hit=[],
            flags={},
            chapter_history=[],
        ),
        conversation=[],
        memories={},
        chapter_summaries=[],
        save_path=save_path,
    )


# --- Test: character agent forwards thinking tokens ---


class TestCharacterThinkingCallback:
    @pytest.mark.asyncio
    async def test_thinking_tokens_forwarded_with_flag(self, tmp_path: Path):
        """Character agent calls on_token(token, True) for thinking."""
        from theact.agents.character import run_character

        game = _make_game(tmp_path)
        char = game.characters["maya"]
        config = LLMConfig(api_key="test")
        narrator_output = NarratorOutput(
            narration="You see Maya.",
            responding_characters=["maya"],
            mood="calm",
        )

        received: list[tuple[str, bool]] = []

        async def on_token(token: str, is_thinking: bool) -> None:
            received.append((token, is_thinking))

        with patch("theact.agents.character.stream") as mock_stream:

            async def fake_stream(*args, **kwargs):
                async def gen():
                    yield StreamChunk(thinking="Let me think...")
                    yield StreamChunk(content="I say hello.")
                    yield StreamChunk(finish_reason="stop")

                return gen()

            mock_stream.side_effect = fake_stream

            result = await run_character(
                game=game,
                character=char,
                memory=None,
                player_input="hello",
                narrator_output=narrator_output,
                prior_responses=[],
                llm_config=config,
                on_token=on_token,
            )

        thinking_calls = [(t, f) for t, f in received if f is True]
        content_calls = [(t, f) for t, f in received if f is False]

        assert len(thinking_calls) >= 1
        assert thinking_calls[0][0] == "Let me think..."

        assert len(content_calls) >= 1
        assert content_calls[0][0] == "I say hello."

        assert isinstance(result, CharacterResponse)
        assert result.thinking == "Let me think..."

    @pytest.mark.asyncio
    async def test_content_only_has_no_thinking_flag(self, tmp_path: Path):
        """Content-only stream calls on_token(token, False) — no thinking."""
        from theact.agents.character import run_character

        game = _make_game(tmp_path)
        char = game.characters["maya"]
        config = LLMConfig(api_key="test")
        narrator_output = NarratorOutput(
            narration="You see Maya.",
            responding_characters=["maya"],
            mood="calm",
        )

        received: list[tuple[str, bool]] = []

        async def on_token(token: str, is_thinking: bool) -> None:
            received.append((token, is_thinking))

        with patch("theact.agents.character.stream") as mock_stream:

            async def fake_stream(*args, **kwargs):
                async def gen():
                    yield StreamChunk(content="Just content.")
                    yield StreamChunk(finish_reason="stop")

                return gen()

            mock_stream.side_effect = fake_stream

            await run_character(
                game=game,
                character=char,
                memory=None,
                player_input="hello",
                narrator_output=narrator_output,
                prior_responses=[],
                llm_config=config,
                on_token=on_token,
            )

        assert all(f is False for _, f in received)
        assert any("Just content." in t for t, _ in received)


# --- Test: narrator agent forwards thinking tokens ---


class TestNarratorThinkingCallback:
    @pytest.mark.asyncio
    async def test_thinking_tokens_forwarded(self, tmp_path: Path):
        """Narrator agent calls on_token(token, True) for thinking."""
        import asyncio

        from theact.agents.narrator import run_narrator

        game = _make_game(tmp_path, characters={})
        config = LLMConfig(api_key="test")

        received: list[tuple[str, bool]] = []

        async def on_token(token: str, is_thinking: bool) -> None:
            received.append((token, is_thinking))

        yaml_content = (
            "```yaml\n"
            "narration: You look around.\n"
            "responding_characters: []\n"
            "mood: calm\n"
            "```"
        )

        result_data = StructuredResult(
            data={
                "narration": "You look around.",
                "responding_characters": [],
                "mood": "calm",
            },
            raw_content=yaml_content,
            thinking="Planning the scene...",
            attempts=1,
        )

        with patch("theact.agents.narrator.stream_structured") as mock_ss:
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            future.set_result(result_data)

            async def fake_stream_structured(*args, **kwargs):
                async def gen():
                    yield StreamChunk(thinking="Planning the scene...")
                    yield StreamChunk(content=yaml_content)

                return gen(), future

            mock_ss.side_effect = fake_stream_structured

            result = await run_narrator(
                game=game,
                player_input="look around",
                llm_config=config,
                on_token=on_token,
            )

        thinking_calls = [(t, f) for t, f in received if f is True]
        content_calls = [(t, f) for t, f in received if f is False]

        assert len(thinking_calls) >= 1
        assert "Planning the scene..." in thinking_calls[0][0]

        assert len(content_calls) >= 1

        assert result.narration == "You look around."
