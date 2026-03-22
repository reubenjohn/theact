"""Extra tests for BrainstormSession.run() and _summarize()."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.conftest import creator_config, make_mock_client
from theact.creator.brainstorm import BrainstormSession, _get_input


class TestGetInput:
    def test_returns_stripped_input(self):
        with patch("theact.creator.brainstorm.console") as mock_console:
            mock_console.input.return_value = "  hello world  "
            result = _get_input()
            assert result == "hello world"

    def test_returns_none_on_eof(self):
        with patch("theact.creator.brainstorm.console") as mock_console:
            mock_console.input.side_effect = EOFError()
            result = _get_input()
            assert result is None

    def test_returns_none_on_keyboard_interrupt(self):
        with patch("theact.creator.brainstorm.console") as mock_console:
            mock_console.input.side_effect = KeyboardInterrupt()
            result = _get_input()
            assert result is None


@pytest.mark.asyncio
class TestBrainstormSessionRun:
    async def test_run_returns_none_on_immediate_abort(self):
        """User sends None (Ctrl-C) immediately -> returns None."""
        client = make_mock_client(["unused"])
        session = BrainstormSession(client, creator_config())

        with patch("theact.creator.brainstorm._get_input", return_value=None):
            with patch("theact.creator.brainstorm.console"):
                result = await session.run()

        assert result is None

    async def test_run_returns_none_on_done_without_conversation(self):
        """User says 'done' before any exchange -> returns None."""
        client = make_mock_client(["unused"])
        session = BrainstormSession(client, creator_config())

        with patch("theact.creator.brainstorm._get_input", return_value="done"):
            with patch("theact.creator.brainstorm.console"):
                result = await session.run()

        assert result is None

    async def test_run_returns_concept_after_conversation(self):
        """User has a conversation then says 'done' -> returns summarized concept."""
        # LLM responses: 1st for the brainstorm reply, 2nd for the summary
        client = make_mock_client(
            [
                "Great idea! A noir mystery in 1940s LA.",
                "A noir detective game set in 1940s Los Angeles.",
            ]
        )
        session = BrainstormSession(client, creator_config())

        inputs = iter(["I want a noir game", "done"])
        with patch(
            "theact.creator.brainstorm._get_input",
            side_effect=lambda *a, **k: next(inputs),
        ):
            with patch("theact.creator.brainstorm.console"):
                result = await session.run()

        assert result is not None
        assert "noir" in result.lower()

    async def test_run_handles_ok_as_done(self):
        """'ok' is treated the same as 'done'."""
        client = make_mock_client(
            [
                "I like your sci-fi concept.",
                "A sci-fi survival game on a space station.",
            ]
        )
        session = BrainstormSession(client, creator_config())

        inputs = iter(["sci-fi survival", "ok"])
        with patch(
            "theact.creator.brainstorm._get_input",
            side_effect=lambda *a, **k: next(inputs),
        ):
            with patch("theact.creator.brainstorm.console"):
                result = await session.run()

        assert result is not None

    async def test_run_handles_lets_make_this(self):
        """'let's make this' is treated the same as 'done'."""
        client = make_mock_client(
            [
                "Fantasy game sounds great!",
                "A fantasy RPG in a medieval kingdom.",
            ]
        )
        session = BrainstormSession(client, creator_config())

        inputs = iter(["fantasy RPG", "let's make this"])
        with patch(
            "theact.creator.brainstorm._get_input",
            side_effect=lambda *a, **k: next(inputs),
        ):
            with patch("theact.creator.brainstorm.console"):
                result = await session.run()

        assert result is not None

    async def test_run_multi_turn_conversation(self):
        """Multiple exchanges before 'done' produces a summary."""
        client = make_mock_client(
            [
                "Interesting! Tell me more.",
                "I like the detective angle.",
                "A noir detective game with moral choices.",
            ]
        )
        session = BrainstormSession(client, creator_config())

        inputs = iter(["noir mystery", "add a detective protagonist", "done"])
        with patch(
            "theact.creator.brainstorm._get_input",
            side_effect=lambda *a, **k: next(inputs),
        ):
            with patch("theact.creator.brainstorm.console"):
                result = await session.run()

        assert result is not None
        assert len(session.messages) > 1  # System + exchanges


@pytest.mark.asyncio
class TestBrainstormSessionSummarize:
    async def test_summarize_calls_llm_with_conversation(self):
        """_summarize() formats conversation and calls the LLM."""
        client = make_mock_client(["A pirate adventure game."])
        session = BrainstormSession(client, creator_config())
        session.messages.append({"role": "user", "content": "pirate game"})
        session.messages.append({"role": "assistant", "content": "Great!"})
        session.messages.append({"role": "user", "content": "with treasure hunting"})
        session.messages.append({"role": "assistant", "content": "Love it!"})

        summary = await session._summarize()
        assert summary == "A pirate adventure game."

    async def test_summarize_includes_all_exchanges(self):
        """The formatted conversation passed to _summarize includes all turns."""
        client = make_mock_client(["summary"])
        session = BrainstormSession(client, creator_config())
        session.messages.append({"role": "user", "content": "idea 1"})
        session.messages.append({"role": "assistant", "content": "response 1"})
        session.messages.append({"role": "user", "content": "idea 2"})
        session.messages.append({"role": "assistant", "content": "response 2"})

        formatted = session._format_conversation()
        assert "User: idea 1" in formatted
        assert "Designer: response 1" in formatted
        assert "User: idea 2" in formatted
        assert "Designer: response 2" in formatted
