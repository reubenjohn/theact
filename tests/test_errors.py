"""Tests for LLM error types."""

from theact.llm.errors import (
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
)


class TestErrorHierarchy:
    def test_connection_error_is_llm_error(self):
        e = LLMConnectionError("cannot connect")
        assert isinstance(e, LLMError)

    def test_rate_limit_error_is_llm_error(self):
        e = LLMRateLimitError("too many requests")
        assert isinstance(e, LLMError)

    def test_response_error_is_llm_error(self):
        e = LLMResponseError("server error")
        assert isinstance(e, LLMError)


class TestLLMRateLimitError:
    def test_retry_after(self):
        e = LLMRateLimitError("rate limited", retry_after=30.0)
        assert e.retry_after == 30.0

    def test_retry_after_none(self):
        e = LLMRateLimitError("rate limited")
        assert e.retry_after is None
