"""Settings persistence: load/save web-configurable settings to settings.yaml.

Provides a SettingsData dataclass with all web-configurable settings, plus
load_settings() and save_settings() functions that read/write settings.yaml.

Lives in io/ (not web/) so both llm/config.py and the web layer can import
without creating a core-to-web dependency.

Load order: env vars (from .env via dotenv) -> settings.yaml overrides
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Settings file path — resolves relative to THEACT_DATA_DIR if set,
# otherwise relative to the working directory (same strategy as save_manager).
_DATA_DIR = os.environ.get("THEACT_DATA_DIR")
SETTINGS_FILE = (
    Path(_DATA_DIR) / "settings.yaml" if _DATA_DIR else Path("settings.yaml")
)


@dataclass
class SettingsData:
    """All web-configurable settings with defaults."""

    # LLM config
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    llm_temperature: float = 1.0
    llm_max_tokens: int = 1500
    llm_context_limit: int = 8192

    # Creator config
    creator_use_same: bool = True
    creator_api_key: str = ""
    creator_base_url: str = "https://api.openai.com/v1"
    creator_model: str = ""

    # Display preferences
    default_show_thinking: bool = False
    font_size: str = "medium"  # small | medium | large
    density: str = "comfortable"  # compact | comfortable


def load_settings() -> SettingsData:
    """Load settings from settings.yaml, falling back to env vars.

    Priority: settings.yaml value > env var > dataclass default.
    """
    settings = SettingsData()

    # Layer 1: env vars (from .env via dotenv)
    settings.llm_api_key = os.environ.get("LLM_API_KEY", settings.llm_api_key)
    settings.llm_base_url = os.environ.get("LLM_BASE_URL", settings.llm_base_url)
    settings.llm_model = os.environ.get("LLM_MODEL", settings.llm_model)
    settings.creator_api_key = os.environ.get(
        "CREATOR_API_KEY", settings.creator_api_key
    )
    settings.creator_base_url = os.environ.get(
        "CREATOR_BASE_URL", settings.creator_base_url
    )
    settings.creator_model = os.environ.get("CREATOR_MODEL", settings.creator_model)

    # Layer 2: settings.yaml overrides
    if SETTINGS_FILE.exists():
        try:
            data = yaml.safe_load(SETTINGS_FILE.read_text()) or {}
            for key, value in data.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
        except Exception:
            logger.warning("Failed to load settings.yaml, using defaults")

    return settings


def save_settings(settings: SettingsData) -> None:
    """Persist settings to settings.yaml.

    API keys are saved here (masked in the UI, never logged).
    The .env file is NOT modified. Empty API keys are omitted
    so that env vars remain the fallback.
    """
    data = asdict(settings)

    # Remove empty API keys so env vars remain the fallback
    if not data.get("llm_api_key"):
        data.pop("llm_api_key", None)
    if not data.get("creator_api_key"):
        data.pop("creator_api_key", None)

    SETTINGS_FILE.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


async def test_llm_connection(
    api_key: str, base_url: str, model: str
) -> tuple[bool, str]:
    """Test LLM connection by listing models or making a minimal completion.

    Returns (success: bool, message: str).
    """
    from openai import AsyncOpenAI

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        # Try listing models first (lightweight, no tokens consumed)
        models = await client.models.list()
        return True, f"{len(models.data)} models available"
    except Exception:
        # Fall back to a minimal completion to test auth
        try:
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1,
            )
            return True, f"Model {model} responded"
        except Exception as e2:
            return False, str(e2)
