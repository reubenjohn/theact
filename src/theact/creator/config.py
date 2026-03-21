"""LLM configuration for the game creation agent."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass


@dataclass(frozen=True)
class CreatorLLMConfig:
    """LLM configuration for the game creation agent.

    Uses a separate, more capable model than the gameplay agents.
    Checks CREATOR_* env vars first, then VENICE_* env vars.

    IMPORTANT: The default VENICE_MODEL (olafangensan-glm-4.7-flash-heretic)
    is a 7B model that CANNOT reliably perform game creation. If no
    CREATOR_MODEL is set and the resolved model is the 7B default, a
    warning is printed at session start. The user should set CREATOR_MODEL
    to a capable model (e.g., gpt-4o, claude-sonnet-4-20250514).
    """

    base_url: str = "https://api.venice.ai/api/v1"
    api_key: str = ""
    model: str = "olafangensan-glm-4.7-flash-heretic"
    temperature: float = 0.7  # moderate creativity for game design
    max_tokens: int = 4096  # full generation needs space
    proposal_max_tokens: int = 1500  # proposals are shorter

    @property
    def is_small_model(self) -> bool:
        """True if the resolved model is the 7B gameplay model.
        Game creation requires a larger, more capable model.
        """
        return "heretic" in self.model.lower()


# The 7B model used for gameplay -- game creation should NOT use this.
_GAMEPLAY_MODEL = "olafangensan-glm-4.7-flash-heretic"


def load_creator_config() -> CreatorLLMConfig:
    """Load creator config from environment variables.

    Checks CREATOR_* vars first, falls back to VENICE_* vars.
    Prints a warning if the resolved model is the small 7B gameplay model,
    since game creation requires a more capable model.
    """
    config = CreatorLLMConfig(
        base_url=os.getenv(
            "CREATOR_BASE_URL",
            os.getenv("VENICE_BASE_URL", "https://api.venice.ai/api/v1"),
        ),
        api_key=os.getenv(
            "CREATOR_API_KEY",
            os.getenv("VENICE_API_KEY", ""),
        ),
        model=os.getenv(
            "CREATOR_MODEL",
            os.getenv("VENICE_MODEL", _GAMEPLAY_MODEL),
        ),
    )

    if config.is_small_model:
        warnings.warn(
            "No CREATOR_MODEL set — falling back to the 7B gameplay model "
            f"({config.model}). Game creation works best with a larger model. "
            "Set CREATOR_MODEL=gpt-4o (or similar) in your .env file.",
            stacklevel=2,
        )

    if not config.api_key:
        raise ValueError(
            "No API key found. Set CREATOR_API_KEY or VENICE_API_KEY in .env."
        )

    return config
