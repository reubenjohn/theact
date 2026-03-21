"""Thin wrapper around AsyncOpenAI — singleton client for Venice AI."""

from __future__ import annotations

from openai import AsyncOpenAI

from theact.llm.config import LLMConfig

_client: AsyncOpenAI | None = None


def get_client(config: LLMConfig) -> AsyncOpenAI:
    """Return a singleton AsyncOpenAI client configured for Venice AI.

    NOTE: Once created, the singleton ignores subsequent configs.
    Call reset_client() first if the config has changed.
    """
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )
    return _client


def reset_client() -> None:
    """Reset the singleton. Useful for tests."""
    global _client
    _client = None
