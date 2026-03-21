"""Error types for LLM operations."""

from __future__ import annotations


class LLMError(Exception):
    """Base exception for LLM-related errors."""


class LLMConnectionError(LLMError):
    """Failed to connect to the API endpoint."""


class LLMRateLimitError(LLMError):
    """Rate limited by the API."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMResponseError(LLMError):
    """The API returned an error response."""
