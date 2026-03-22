"""LLM configuration for the game creation agent."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass


@dataclass(frozen=True)
class CreatorLLMConfig:
    """LLM configuration for the game creation agent.

    Uses a separate, more capable model than the gameplay agents.
    Checks CREATOR_* env vars first, then LLM_* env vars.

    All token budgets and temperature are user-configurable via
    settings.yaml or environment variables — no model-name detection.

    Tuning guide:
      Large models (gpt-4o, claude-sonnet, etc.):
        temperature=0.7, max_tokens=4096, proposal_max_tokens=3000
      Small / thinking models (7B-class):
        temperature=0.5, max_tokens=4096, proposal_max_tokens=3000
        (thinking tokens consume the max_tokens budget, so keep it generous)
    """

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    proposal_max_tokens: int = 3000

    def max_tokens_for(self, call_type: str) -> int:
        """Return max_tokens for the given call type.

        call_type: "world", "character", "chapter", "fix", or "proposal"
        """
        if call_type == "proposal":
            return self.proposal_max_tokens
        return self.max_tokens


def load_creator_config() -> CreatorLLMConfig:
    """Load creator config from settings.yaml or environment variables.

    When settings.yaml exists:
      - If creator_use_same is True (or creator fields are empty), uses
        the primary LLM config values for the creator.
      - If creator_use_same is False and creator fields are populated,
        uses the creator-specific values.

    When settings.yaml does not exist, falls back to the original
    env-var-only path (CREATOR_* -> LLM_* -> defaults).
    """
    from theact.io.settings_store import SETTINGS_FILE, load_settings

    if SETTINGS_FILE.exists():
        settings = load_settings()

        # Determine whether to use creator-specific or primary LLM config
        if settings.creator_use_same or not settings.creator_model:
            # Use primary LLM config values
            api_key = settings.llm_api_key or os.getenv("LLM_API_KEY", "")
            base_url = settings.llm_base_url
            model = settings.llm_model or os.getenv("LLM_MODEL", "")
        else:
            # Use creator-specific values
            api_key = (
                settings.creator_api_key
                or settings.llm_api_key
                or os.getenv("CREATOR_API_KEY", "")
                or os.getenv("LLM_API_KEY", "")
            )
            base_url = settings.creator_base_url
            model = settings.creator_model

        config = CreatorLLMConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=settings.creator_temperature,
            max_tokens=settings.creator_max_tokens,
        )
    else:
        # Original env-var-only path (unchanged)
        config = CreatorLLMConfig(
            base_url=os.getenv(
                "CREATOR_BASE_URL",
                os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            ),
            api_key=os.getenv(
                "CREATOR_API_KEY",
                os.getenv("LLM_API_KEY", ""),
            ),
            model=os.getenv(
                "CREATOR_MODEL",
                os.getenv("LLM_MODEL", ""),
            ),
        )

    if not config.model:
        warnings.warn(
            "No model configured for game creation. "
            "Set CREATOR_MODEL (or LLM_MODEL) in .env or Settings.",
            stacklevel=2,
        )

    if not config.api_key:
        raise ValueError(
            "No API key found. Set CREATOR_API_KEY or LLM_API_KEY in .env, "
            "or configure it in Settings."
        )

    return config
