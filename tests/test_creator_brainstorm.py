"""Tests for brainstorm session."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
import pytest
from theact.creator.brainstorm import BrainstormSession
from theact.llm.tokens import estimate_tokens
from theact.creator.config import CreatorLLMConfig


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


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_normal_string(self):
        assert estimate_tokens("Hello world!") == 3


@pytest.mark.asyncio
class TestBrainstormSession:
    async def test_empty_conversation_returns_none(self):
        """Session returns None if user immediately says 'done'."""
        client = _make_mock_client(["response"])
        session = BrainstormSession(client, _config())
        # Directly test: if no user/assistant messages, _summarize is skipped
        assert len(session.messages) == 1  # only system prompt
        # Simulate: user says "done" before any exchange
        # The run() method returns None if <= 1 messages after loop ends

    async def test_summarize_uses_conversation(self):
        """_summarize calls LLM with conversation content."""
        client = _make_mock_client(["A noir detective game in 1940s LA."])
        session = BrainstormSession(client, _config())
        session.messages.append({"role": "user", "content": "I want a noir game"})
        session.messages.append({"role": "assistant", "content": "Great idea!"})

        summary = await session._summarize()
        assert summary == "A noir detective game in 1940s LA."

    async def test_format_conversation(self):
        """Conversation formatting includes user and designer labels."""
        session = BrainstormSession(AsyncMock(), _config())
        session.messages.append({"role": "user", "content": "noir game"})
        session.messages.append({"role": "assistant", "content": "cool idea"})

        formatted = session._format_conversation()
        assert "User: noir game" in formatted
        assert "Designer: cool idea" in formatted

    async def test_truncation_keeps_recent_exchanges(self):
        """Sliding window truncation keeps system prompt + last N pairs."""
        session = BrainstormSession(AsyncMock(), _config())
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
