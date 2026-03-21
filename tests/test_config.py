"""Tests for LLM configuration."""

import pytest

from theact.llm.config import (
    CHARACTER_CONFIG,
    GAME_STATE_CONFIG,
    MEMORY_UPDATE_CONFIG,
    NARRATOR_CONFIG,
    SUMMARIZER_CONFIG,
    AgentLLMConfig,
    LLMConfig,
    load_llm_config,
)


class TestLLMConfig:
    def test_defaults(self):
        config = LLMConfig()
        assert config.base_url == "https://api.venice.ai/api/v1"
        assert config.api_key == ""
        assert config.model == "olafangensan-glm-4.7-flash-heretic"
        assert config.default_temperature == 1.0
        assert config.default_max_tokens == 1500
        assert config.context_limit == 8192

    def test_frozen(self):
        config = LLMConfig()
        with pytest.raises(AttributeError):
            config.api_key = "new_key"  # type: ignore[misc]

    def test_custom_values(self):
        config = LLMConfig(
            base_url="http://localhost:8080",
            api_key="test-key",
            model="test-model",
            default_temperature=0.5,
        )
        assert config.base_url == "http://localhost:8080"
        assert config.api_key == "test-key"
        assert config.model == "test-model"
        assert config.default_temperature == 0.5


class TestAgentLLMConfig:
    def test_defaults(self):
        config = AgentLLMConfig()
        assert config.temperature is None
        assert config.max_tokens is None
        assert config.structured is False
        assert config.max_retries == 2
        assert config.retry_temperature_bump == 0.1

    def test_frozen(self):
        config = AgentLLMConfig()
        with pytest.raises(AttributeError):
            config.temperature = 0.5  # type: ignore[misc]


class TestAgentDefaults:
    def test_narrator_config(self):
        assert NARRATOR_CONFIG.temperature == 1.0
        assert NARRATOR_CONFIG.max_tokens == 2000
        assert NARRATOR_CONFIG.structured is True
        assert NARRATOR_CONFIG.max_retries == 2

    def test_character_config(self):
        assert CHARACTER_CONFIG.temperature == 1.0
        assert CHARACTER_CONFIG.max_tokens == 1500
        assert CHARACTER_CONFIG.structured is False

    def test_memory_update_config(self):
        assert MEMORY_UPDATE_CONFIG.temperature == 0.2
        assert MEMORY_UPDATE_CONFIG.max_tokens == 1500
        assert MEMORY_UPDATE_CONFIG.structured is True

    def test_game_state_config(self):
        assert GAME_STATE_CONFIG.temperature == 0.2
        assert GAME_STATE_CONFIG.max_tokens == 800
        assert GAME_STATE_CONFIG.structured is True

    def test_summarizer_config(self):
        assert SUMMARIZER_CONFIG.temperature == 0.3
        assert SUMMARIZER_CONFIG.max_tokens == 1000
        assert SUMMARIZER_CONFIG.structured is False


class TestLoadLLMConfig:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("VENICE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="VENICE_API_KEY"):
            load_llm_config()

    def test_loads_from_env(self, monkeypatch):
        monkeypatch.setenv("VENICE_API_KEY", "test-key-123")
        monkeypatch.delenv("VENICE_BASE_URL", raising=False)
        monkeypatch.delenv("VENICE_MODEL", raising=False)
        config = load_llm_config()
        assert config.api_key == "test-key-123"
        assert config.base_url == "https://api.venice.ai/api/v1"
        assert config.model == "olafangensan-glm-4.7-flash-heretic"

    def test_custom_env_vars(self, monkeypatch):
        monkeypatch.setenv("VENICE_API_KEY", "my-key")
        monkeypatch.setenv("VENICE_BASE_URL", "http://localhost:1234")
        monkeypatch.setenv("VENICE_MODEL", "custom-model")
        config = load_llm_config()
        assert config.api_key == "my-key"
        assert config.base_url == "http://localhost:1234"
        assert config.model == "custom-model"
