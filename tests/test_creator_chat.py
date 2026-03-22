"""Tests for the brainstorm chat panel backend logic.

Tests the CreatorChatPanel's message handling, truncation, and summarization
without requiring a live NiceGUI server (mocks the UI and LLM).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import creator_config, make_mock_client


class TestChatPanelTruncation:
    """Test the sliding window truncation logic."""

    def test_no_truncation_when_under_budget(self):
        from theact.web.creator_chat import CreatorChatPanel

        panel = CreatorChatPanel(
            client=AsyncMock(), config=creator_config(), on_use_text=None
        )
        panel._messages.append({"role": "user", "content": "short"})
        panel._messages.append({"role": "assistant", "content": "reply"})

        panel._truncate_if_needed()
        # System + 2 messages = 3 total
        assert len(panel._messages) == 3

    def test_truncation_keeps_system_and_recent(self):
        from theact.web.creator_chat import CreatorChatPanel

        panel = CreatorChatPanel(
            client=AsyncMock(), config=creator_config(), on_use_text=None
        )
        # Add enough messages to exceed budget
        for i in range(30):
            panel._messages.append({"role": "user", "content": f"message {i} " * 100})
            panel._messages.append(
                {"role": "assistant", "content": f"reply {i} " * 100}
            )

        panel._truncate_if_needed()
        assert panel._messages[0]["role"] == "system"
        assert len(panel._messages) <= 1 + panel.KEEP_EXCHANGES * 2


@pytest.mark.asyncio
class TestChatPanelSummarize:
    """Test the conversation summarization logic."""

    async def test_summarize_returns_llm_response(self):
        from theact.web.creator_chat import CreatorChatPanel

        client = make_mock_client(["A noir detective game in rainy LA."])
        panel = CreatorChatPanel(
            client=client, config=creator_config(), on_use_text=None
        )
        panel._messages.append({"role": "user", "content": "noir game"})
        panel._messages.append({"role": "assistant", "content": "great idea"})

        summary = await panel._summarize()
        assert summary == "A noir detective game in rainy LA."

    async def test_summarize_formats_conversation(self):
        from theact.web.creator_chat import CreatorChatPanel

        # Use a client that captures the messages sent
        captured_messages = []
        client = AsyncMock()

        async def fake_create(**kwargs):
            captured_messages.append(kwargs.get("messages", []))
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "summary"
            return mock_response

        client.chat.completions.create = fake_create

        panel = CreatorChatPanel(
            client=client, config=creator_config(), on_use_text=None
        )
        panel._messages.append({"role": "user", "content": "noir game"})
        panel._messages.append({"role": "assistant", "content": "cool idea"})

        await panel._summarize()
        # The user content sent to the summarizer should contain both messages
        assert len(captured_messages) == 1
        user_msg = captured_messages[0][-1]["content"]
        assert "User: noir game" in user_msg
        assert "Designer: cool idea" in user_msg


class TestChatPanelUndoAndClear:
    """Test the undo and clear operations."""

    def _panel_with_exchange(self):
        """Create a panel with one user+assistant exchange."""
        from theact.web.creator_chat import CreatorChatPanel

        panel = CreatorChatPanel(
            client=AsyncMock(), config=creator_config(), on_use_text=None
        )
        panel._messages.append({"role": "user", "content": "hello"})
        panel._messages.append({"role": "assistant", "content": "hi there"})
        # Simulate bubble elements (mocks with .delete())
        panel._bubble_elements.append(MagicMock())
        panel._bubble_elements.append(MagicMock())
        return panel

    def test_undo_removes_user_and_assistant(self):
        panel = self._panel_with_exchange()
        assert len(panel._messages) == 3  # system + user + assistant
        panel._undo_last()
        # Only system prompt remains
        assert len(panel._messages) == 1
        assert panel._messages[0]["role"] == "system"
        assert len(panel._bubble_elements) == 0

    def test_undo_removes_only_user_when_no_assistant(self):
        from theact.web.creator_chat import CreatorChatPanel

        panel = CreatorChatPanel(
            client=AsyncMock(), config=creator_config(), on_use_text=None
        )
        panel._messages.append({"role": "user", "content": "hello"})
        panel._bubble_elements.append(MagicMock())
        panel._undo_last()
        assert len(panel._messages) == 1
        assert len(panel._bubble_elements) == 0

    def test_undo_noop_on_empty_chat(self):
        from theact.web.creator_chat import CreatorChatPanel

        panel = CreatorChatPanel(
            client=AsyncMock(), config=creator_config(), on_use_text=None
        )
        panel._undo_last()  # should not raise
        assert len(panel._messages) == 1

    def test_undo_blocked_while_sending(self):
        panel = self._panel_with_exchange()
        panel._sending = True
        panel._undo_last()
        assert len(panel._messages) == 3  # unchanged

    def test_clear_resets_to_system_only(self):
        panel = self._panel_with_exchange()
        panel._chat_container = MagicMock()
        panel._clear_chat()
        assert len(panel._messages) == 1
        assert panel._messages[0]["role"] == "system"
        assert len(panel._bubble_elements) == 0
        panel._chat_container.clear.assert_called_once()

    def test_clear_blocked_while_sending(self):
        panel = self._panel_with_exchange()
        panel._sending = True
        panel._clear_chat()
        assert len(panel._messages) == 3  # unchanged

    def test_truncation_keeps_bubbles_in_sync(self):
        from theact.web.creator_chat import CreatorChatPanel

        panel = CreatorChatPanel(
            client=AsyncMock(), config=creator_config(), on_use_text=None
        )
        for i in range(30):
            panel._messages.append({"role": "user", "content": f"msg {i} " * 100})
            panel._messages.append(
                {"role": "assistant", "content": f"reply {i} " * 100}
            )
            panel._bubble_elements.append(MagicMock())
            panel._bubble_elements.append(MagicMock())

        panel._truncate_if_needed()
        non_system = len(panel._messages) - 1
        assert len(panel._bubble_elements) == non_system
