"""Extra tests for creator config covering the env-var-only fallback path.

The existing tests for load_creator_config() go through the settings-file
path when SETTINGS_FILE.exists() is True. These tests monkeypatch
SETTINGS_FILE.exists() to False so we exercise the env-var-only fallback.
"""

from __future__ import annotations

import warnings
from unittest.mock import patch

import pytest

from theact.creator.config import CreatorLLMConfig, load_creator_config

# The SETTINGS_FILE is imported locally inside load_creator_config() from
# theact.io.settings_store, so we must patch it there.
_SETTINGS_FILE_PATH = "theact.io.settings_store.SETTINGS_FILE"


class TestEnvVarOnlyFallback:
    """Tests for load_creator_config() when settings.yaml does NOT exist."""

    def test_creator_vars_only(self, monkeypatch):
        """CREATOR_* env vars are used when settings.yaml doesn't exist."""
        monkeypatch.setenv("CREATOR_API_KEY", "creator-key")
        monkeypatch.setenv("CREATOR_BASE_URL", "http://creator-host")
        monkeypatch.setenv("CREATOR_MODEL", "gpt-4o")
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        with patch(_SETTINGS_FILE_PATH) as mock_file:
            mock_file.exists.return_value = False
            config = load_creator_config()

        assert config.api_key == "creator-key"
        assert config.base_url == "http://creator-host"
        assert config.model == "gpt-4o"

    def test_llm_vars_fallback(self, monkeypatch):
        """LLM_* env vars are used as fallback when CREATOR_* are not set."""
        monkeypatch.delenv("CREATOR_API_KEY", raising=False)
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
        monkeypatch.delenv("CREATOR_MODEL", raising=False)
        monkeypatch.setenv("LLM_API_KEY", "llm-key")
        monkeypatch.setenv("LLM_BASE_URL", "http://llm-host")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")

        with patch(_SETTINGS_FILE_PATH) as mock_file:
            mock_file.exists.return_value = False
            config = load_creator_config()

        assert config.api_key == "llm-key"
        assert config.base_url == "http://llm-host"
        assert config.model == "gpt-4o"

    def test_creator_vars_take_precedence(self, monkeypatch):
        """CREATOR_* takes precedence over LLM_* in env-var-only path."""
        monkeypatch.setenv("CREATOR_API_KEY", "creator-key")
        monkeypatch.setenv("CREATOR_BASE_URL", "http://creator-host")
        monkeypatch.setenv("CREATOR_MODEL", "creator-model")
        monkeypatch.setenv("LLM_API_KEY", "llm-key")
        monkeypatch.setenv("LLM_BASE_URL", "http://llm-host")
        monkeypatch.setenv("LLM_MODEL", "llm-model")

        with patch(_SETTINGS_FILE_PATH) as mock_file:
            mock_file.exists.return_value = False
            config = load_creator_config()

        assert config.api_key == "creator-key"
        assert config.base_url == "http://creator-host"
        assert config.model == "creator-model"

    def test_no_model_warns(self, monkeypatch):
        """When no model is set, a warning is emitted."""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.delenv("CREATOR_API_KEY", raising=False)
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
        monkeypatch.delenv("CREATOR_MODEL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)

        with patch(_SETTINGS_FILE_PATH) as mock_file:
            mock_file.exists.return_value = False
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                config = load_creator_config()
                assert len(w) == 1
                assert "No model configured" in str(w[0].message)

        assert config.model == ""

    def test_default_base_url(self, monkeypatch):
        """Default base_url is OpenAI when no env vars set."""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.delenv("CREATOR_API_KEY", raising=False)
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
        monkeypatch.delenv("CREATOR_MODEL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)

        with patch(_SETTINGS_FILE_PATH) as mock_file:
            mock_file.exists.return_value = False
            config = load_creator_config()

        assert config.base_url == "https://api.openai.com/v1"

    def test_missing_api_key_raises(self, monkeypatch):
        """ValueError raised when no API key is available anywhere."""
        monkeypatch.delenv("CREATOR_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("CREATOR_MODEL", raising=False)
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)

        with patch(_SETTINGS_FILE_PATH) as mock_file:
            mock_file.exists.return_value = False
            with pytest.raises(ValueError, match="No API key found"):
                load_creator_config()

    def test_no_warning_when_model_set(self, monkeypatch):
        """No warning emitted when a model is explicitly configured."""
        monkeypatch.setenv("CREATOR_API_KEY", "test-key")
        monkeypatch.setenv("CREATOR_MODEL", "gpt-4o")
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)

        with patch(_SETTINGS_FILE_PATH) as mock_file:
            mock_file.exists.return_value = False
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                load_creator_config()
                assert len(w) == 0


class TestMaxTokensFor:
    """Cover max_tokens_for() call_type routing."""

    def test_proposal_returns_proposal_max_tokens(self):
        config = CreatorLLMConfig(proposal_max_tokens=1500, max_tokens=4096)
        assert config.max_tokens_for("proposal") == 1500

    def test_other_returns_max_tokens(self):
        config = CreatorLLMConfig(max_tokens=4096)
        assert config.max_tokens_for("world") == 4096
        assert config.max_tokens_for("character") == 4096
        assert config.max_tokens_for("chapter") == 4096
        assert config.max_tokens_for("fix") == 4096
