"""LLM configuration: global settings and per-agent overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LLMConfig:
    """Global LLM configuration. One instance per game session."""

    base_url: str = "https://api.venice.ai/api/v1"
    api_key: str = ""  # loaded from env
    model: str = "olafangensan-glm-4.7-flash-heretic"
    default_temperature: float = 1.0
    default_max_tokens: int = 1500
    context_limit: int = 8192  # model's context window size


@dataclass(frozen=True)
class AgentLLMConfig:
    """Per-agent-type overrides. Merged with LLMConfig at call time."""

    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    structured: bool = False  # whether to parse YAML from response
    max_retries: int = 2  # retries on YAML parse failure
    retry_temperature_bump: float = 0.1  # increase temp on each retry


# Sensible defaults for each agent type.
# NOTE: This is a thinking model — thinking tokens count against max_tokens.
# Budget must include ~500-1500 tokens for reasoning PLUS the actual content.
NARRATOR_CONFIG = AgentLLMConfig(
    temperature=1.0,
    max_tokens=2000,
    structured=True,
    max_retries=2,
)

CHARACTER_CONFIG = AgentLLMConfig(
    temperature=1.0,
    max_tokens=1500,
    structured=False,
)

MEMORY_UPDATE_CONFIG = AgentLLMConfig(
    temperature=0.2,
    max_tokens=1500,
    structured=True,
    max_retries=2,
)

GAME_STATE_CONFIG = AgentLLMConfig(
    temperature=0.2,
    max_tokens=800,
    structured=True,
    max_retries=2,
)

SUMMARIZER_CONFIG = AgentLLMConfig(
    temperature=0.3,
    max_tokens=1000,
    structured=False,
)


def load_llm_config() -> LLMConfig:
    """Load LLM configuration from environment variables."""
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        raise ValueError(
            "VENICE_API_KEY environment variable is required. "
            "Set it in your .env file or shell environment."
        )

    return LLMConfig(
        base_url=os.environ.get("VENICE_BASE_URL", "https://api.venice.ai/api/v1"),
        api_key=api_key,
        model=os.environ.get("VENICE_MODEL", "olafangensan-glm-4.7-flash-heretic"),
    )
