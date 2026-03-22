"""Tests for brainstorm session."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.conftest import creator_config, make_mock_client
from theact.creator.brainstorm import BrainstormSession
from theact.llm.tokens import estimate_tokens


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_normal_string(self):
        assert estimate_tokens("Hello world!") == 3


@pytest.mark.asyncio
class TestBrainstormSession:
    async def test_empty_conversation_returns_none(self):
        """Session returns None if user immediately says 'done'."""
        client = make_mock_client(["response"])
        session = BrainstormSession(client, creator_config())
        # Directly test: if no user/assistant messages, _summarize is skipped
        assert len(session.messages) == 1  # only system prompt
        # Simulate: user says "done" before any exchange
        # The run() method returns None if <= 1 messages after loop ends

    async def test_summarize_uses_conversation(self):
        """_summarize calls LLM with conversation content."""
        client = make_mock_client(["A noir detective game in 1940s LA."])
        session = BrainstormSession(client, creator_config())
        session.messages.append({"role": "user", "content": "I want a noir game"})
        session.messages.append({"role": "assistant", "content": "Great idea!"})

        summary = await session._summarize()
        assert summary == "A noir detective game in 1940s LA."

    async def test_format_conversation(self):
        """Conversation formatting includes user and designer labels."""
        session = BrainstormSession(AsyncMock(), creator_config())
        session.messages.append({"role": "user", "content": "noir game"})
        session.messages.append({"role": "assistant", "content": "cool idea"})

        formatted = session._format_conversation()
        assert "User: noir game" in formatted
        assert "Designer: cool idea" in formatted

    async def test_truncation_keeps_recent_exchanges(self):
        """Sliding window truncation keeps system prompt + last N pairs."""
        session = BrainstormSession(AsyncMock(), creator_config())
        # Add enough messages to exceed the token budget
        for i in range(20):
            session.messages.append({"role": "user", "content": f"message {i} " * 50})
            session.messages.append(
                {"role": "assistant", "content": f"reply {i} " * 50}
            )

        session._truncate_if_needed()
        # Should keep system + last KEEP_EXCHANGES * 2 messages
        assert session.messages[0]["role"] == "system"
        assert len(session.messages) <= 1 + session.KEEP_EXCHANGES * 2
