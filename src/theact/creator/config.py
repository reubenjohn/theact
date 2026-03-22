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

    IMPORTANT: Small 7B-class models cannot reliably perform game creation.
    If no CREATOR_MODEL is set and the resolved model is a small default,
    a warning is printed at session start. The user should set CREATOR_MODEL
    to a capable model (e.g., gpt-4o, claude-sonnet-4-20250514).
    """

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7  # moderate creativity for game design
    max_tokens: int = 4096  # large model default
    proposal_max_tokens: int = 3000  # generous to accommodate thinking models

    # Small model overrides (applied when is_small_model is True)
    small_model_world_max_tokens: int = 800
    small_model_character_max_tokens: int = 800
    small_model_chapter_max_tokens: int = 1000
    small_model_fix_max_tokens: int = 600
    small_model_temperature: float = 0.5

    @property
    def is_small_model(self) -> bool:
        """True if the resolved model is the 7B gameplay model.
        Game creation requires a larger, more capable model.
        """
        return "heretic" in self.model.lower()

    def max_tokens_for(self, call_type: str) -> int:
        """Return max_tokens for the given call type.

        call_type: "world", "character", "chapter", "fix", or "proposal"
        """
        if not self.is_small_model:
            return (
                self.max_tokens if call_type != "proposal" else self.proposal_max_tokens
            )
        return {
            "world": self.small_model_world_max_tokens,
            "character": self.small_model_character_max_tokens,
            "chapter": self.small_model_chapter_max_tokens,
            "fix": self.small_model_fix_max_tokens,
            "proposal": self.proposal_max_tokens,
        }.get(call_type, self.small_model_world_max_tokens)

    @property
    def generation_temperature(self) -> float:
        return self.small_model_temperature if self.is_small_model else self.temperature


# The 7B model used for gameplay -- game creation should NOT use this.
_GAMEPLAY_MODEL = "olafangensan-glm-4.7-flash-heretic"


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
            model = settings.llm_model or os.getenv("LLM_MODEL", _GAMEPLAY_MODEL)
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
                os.getenv("LLM_MODEL", _GAMEPLAY_MODEL),
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
            "No API key found. Set CREATOR_API_KEY or LLM_API_KEY in .env, "
            "or configure it in Settings."
        )

    return config
