"""Tests for token estimation utilities."""

from theact.llm.tokens import (
    CHARS_PER_TOKEN,
    MESSAGE_OVERHEAD_TOKENS,
    estimate_messages_tokens,
    estimate_tokens,
    tokens_remaining,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        # "Hi" is 2 chars -> 2 // 4 = 0, but min is 1
        assert estimate_tokens("Hi") == 1

    def test_known_length(self):
        # 40 chars -> 40 // 4 = 10
        text = "a" * 40
        assert estimate_tokens(text) == 10

    def test_typical_english(self):
        text = "Hello, world! This is a test of token estimation."
        expected = len(text) // CHARS_PER_TOKEN
        assert estimate_tokens(text) == expected

    def test_long_text(self):
        text = "word " * 1000  # 5000 chars
        assert estimate_tokens(text) == 5000 // CHARS_PER_TOKEN

    def test_minimum_one_token(self):
        # Any non-empty string is at least 1 token
        assert estimate_tokens("x") == 1
        assert estimate_tokens("ab") == 1
        assert estimate_tokens("abc") == 1


class TestEstimateMessagesTokens:
    def test_empty_messages(self):
        # Just the base overhead of 3
        assert estimate_messages_tokens([]) == 3

    def test_single_message(self):
        messages = [{"role": "user", "content": "Hello!"}]
        # MESSAGE_OVERHEAD_TOKENS + tokens("Hello!") + tokens("user") + base 3
        expected = (
            MESSAGE_OVERHEAD_TOKENS
            + estimate_tokens("Hello!")
            + estimate_tokens("user")
            + 3
        )
        assert estimate_messages_tokens(messages) == expected

    def test_multiple_messages(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        result = estimate_messages_tokens(messages)
        # Should be positive and reasonable
        assert result > 0
        assert result > len(messages) * MESSAGE_OVERHEAD_TOKENS

    def test_message_without_content(self):
        # Should handle missing content gracefully
        messages = [{"role": "user"}]
        result = estimate_messages_tokens(messages)
        assert result > 0


class TestTokensRemaining:
    def test_plenty_of_budget(self):
        messages = [{"role": "user", "content": "Hi"}]
        remaining = tokens_remaining(
            messages, context_limit=8192, max_completion_tokens=900
        )
        assert remaining > 0
        assert remaining < 8192

    def test_over_budget(self):
        # Create a very long message that exceeds the context limit
        messages = [{"role": "user", "content": "x" * 40000}]
        remaining = tokens_remaining(
            messages, context_limit=8192, max_completion_tokens=900
        )
        assert remaining < 0

    def test_exact_calculation(self):
        messages = [{"role": "user", "content": "Hello"}]
        used = estimate_messages_tokens(messages)
        remaining = tokens_remaining(
            messages, context_limit=1000, max_completion_tokens=200
        )
        assert remaining == 1000 - used - 200
