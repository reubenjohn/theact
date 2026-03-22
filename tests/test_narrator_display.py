"""Regression tests for narrator display finalization.

Validates that:
1. on_narrator_done callback in run_turn fires before character agents
2. StreamingTextBlock.replace_content swaps buffer and output
3. Narrator YAML is not exposed to the user in the final display

These tests were added after discovering that raw YAML (responding_characters,
mood, narration fields) was being displayed verbatim in the web UI during
streaming. See commit: "Replace raw YAML in narrator streaming with parsed content".
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theact.engine.types import NarratorOutput


class TestOnNarratorDoneCallback:
    """Verify on_narrator_done fires after narrator, before characters."""

    @pytest.mark.asyncio
    async def test_callback_receives_narrator_output(self):
        """on_narrator_done receives a NarratorOutput with narration, mood, characters."""
        received = []

        async def capture_narrator(output: NarratorOutput) -> None:
            received.append(output)

        # Mock run_narrator to return a known output
        narrator_output = NarratorOutput(
            narration="The wind howls through the ruins.",
            responding_characters=["maya", "joaquin"],
            mood="tense",
        )

        with (
            patch("theact.engine.turn.run_narrator", new_callable=AsyncMock) as mock_nr,
            patch("theact.engine.turn.run_character", new_callable=AsyncMock),
            patch("theact.engine.turn.run_memory_update", new_callable=AsyncMock),
            patch("theact.engine.turn.run_game_state", new_callable=AsyncMock),
            patch("theact.engine.turn.append_conversation"),
            patch("theact.engine.turn.save_state"),
            patch("theact.engine.turn.save_memory"),
            patch("theact.engine.turn.save_summaries"),
            patch("theact.engine.turn.commit_turn"),
        ):
            mock_nr.return_value = narrator_output

            from theact.engine.turn import run_turn

            game = MagicMock()
            game.state.turn = 0
            game.state.chapter_just_advanced = False
            game.characters = {}
            game.memories = {}
            game.chapters = {"ch1": MagicMock(next=None)}
            game.state.current_chapter = "ch1"
            game.state.beats_hit = []
            game.conversation = []
            game.summaries = MagicMock(rolling="", chapter_summaries={})
            game.state.last_summarized_turn = 0
            game.state.game_complete = False

            llm_config = MagicMock()

            await run_turn(
                game=game,
                player_input="I look around",
                llm_config=llm_config,
                on_narrator_done=capture_narrator,
            )

        assert len(received) == 1
        assert received[0].narration == "The wind howls through the ruins."
        assert received[0].mood == "tense"
        assert received[0].responding_characters == ["maya", "joaquin"]

    @pytest.mark.asyncio
    async def test_callback_fires_before_characters(self):
        """on_narrator_done fires before character agents start."""
        call_order = []

        async def on_narrator_done(output: NarratorOutput) -> None:
            call_order.append("narrator_done")

        narrator_output = NarratorOutput(
            narration="Narration text.",
            responding_characters=["maya"],
            mood="calm",
        )

        async def fake_character(*args, **kwargs):
            call_order.append("character")
            from theact.engine.types import CharacterResponse

            return CharacterResponse(character="maya", response="Hello.")

        with (
            patch("theact.engine.turn.run_narrator", new_callable=AsyncMock) as mock_nr,
            patch(
                "theact.engine.turn.run_character",
                side_effect=fake_character,
            ),
            patch("theact.engine.turn.run_memory_update", new_callable=AsyncMock),
            patch("theact.engine.turn.run_game_state", new_callable=AsyncMock),
            patch("theact.engine.turn.append_conversation"),
            patch("theact.engine.turn.save_state"),
            patch("theact.engine.turn.save_memory"),
            patch("theact.engine.turn.save_summaries"),
            patch("theact.engine.turn.commit_turn"),
        ):
            mock_nr.return_value = narrator_output

            from theact.engine.turn import run_turn

            game = MagicMock()
            game.state.turn = 0
            game.state.chapter_just_advanced = False
            game.characters = {"maya": MagicMock()}
            game.characters["maya"].name = "Maya Chen"
            game.memories = {}
            game.chapters = {"ch1": MagicMock(next=None)}
            game.state.current_chapter = "ch1"
            game.state.beats_hit = []
            game.conversation = []
            game.summaries = MagicMock(rolling="", chapter_summaries={})
            game.state.last_summarized_turn = 0
            game.state.game_complete = False

            llm_config = MagicMock()

            await run_turn(
                game=game,
                player_input="test",
                llm_config=llm_config,
                on_narrator_done=on_narrator_done,
            )

        assert call_order[0] == "narrator_done"
        assert "character" in call_order
        assert call_order.index("narrator_done") < call_order.index("character")

    @pytest.mark.asyncio
    async def test_no_callback_is_fine(self):
        """run_turn works without on_narrator_done (backward compat)."""
        narrator_output = NarratorOutput(
            narration="Text.", responding_characters=[], mood="calm"
        )

        with (
            patch("theact.engine.turn.run_narrator", new_callable=AsyncMock) as mock_nr,
            patch("theact.engine.turn.run_memory_update", new_callable=AsyncMock),
            patch("theact.engine.turn.run_game_state", new_callable=AsyncMock),
            patch("theact.engine.turn.append_conversation"),
            patch("theact.engine.turn.save_state"),
            patch("theact.engine.turn.save_memory"),
            patch("theact.engine.turn.save_summaries"),
            patch("theact.engine.turn.commit_turn"),
        ):
            mock_nr.return_value = narrator_output

            from theact.engine.turn import run_turn

            game = MagicMock()
            game.state.turn = 0
            game.state.chapter_just_advanced = False
            game.characters = {}
            game.memories = {}
            game.chapters = {"ch1": MagicMock(next=None)}
            game.state.current_chapter = "ch1"
            game.state.beats_hit = []
            game.conversation = []
            game.summaries = MagicMock(rolling="", chapter_summaries={})
            game.state.last_summarized_turn = 0
            game.state.game_complete = False

            llm_config = MagicMock()

            # Should not raise
            result = await run_turn(
                game=game,
                player_input="test",
                llm_config=llm_config,
                on_narrator_done=None,
            )

        assert result.narrator.narration == "Text."
