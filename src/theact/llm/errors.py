"""Error types for LLM operations."""

from __future__ import annotations

from enum import Enum


class ParseFailureType(str, Enum):
    """Classification of structured output parse failures."""

    success = "success"
    no_yaml_block = "no_yaml_block"
    invalid_yaml = "invalid_yaml"
    wrong_schema = "wrong_schema"
    empty_response = "empty_response"
    echo_prompt = "echo_prompt"
    json_instead = "json_instead"


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
