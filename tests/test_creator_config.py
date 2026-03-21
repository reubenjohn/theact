"""Tests for creator LLM configuration."""

import warnings

import pytest

from theact.creator.config import CreatorLLMConfig, _GAMEPLAY_MODEL, load_creator_config


class TestCreatorLLMConfig:
    def test_defaults(self):
        config = CreatorLLMConfig()
        assert config.base_url == "https://api.openai.com/v1"
        assert config.api_key == ""
        assert config.model == ""
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.proposal_max_tokens == 1500

    def test_frozen(self):
        config = CreatorLLMConfig()
        with pytest.raises(AttributeError):
            config.api_key = "new"  # type: ignore[misc]

    def test_custom_values(self):
        config = CreatorLLMConfig(
            base_url="http://localhost:8080",
            api_key="test-key",
            model="gpt-4o",
            temperature=0.5,
        )
        assert config.base_url == "http://localhost:8080"
        assert config.api_key == "test-key"
        assert config.model == "gpt-4o"
        assert config.temperature == 0.5

    def test_is_small_model_true_for_7b(self):
        config = CreatorLLMConfig(model=_GAMEPLAY_MODEL)
        assert config.is_small_model is True

    def test_is_small_model_false_for_large_model(self):
        config = CreatorLLMConfig(model="gpt-4o")
        assert config.is_small_model is False

    def test_is_small_model_case_insensitive(self):
        config = CreatorLLMConfig(model="Some-HERETIC-Model")
        assert config.is_small_model is True


class TestLoadCreatorConfig:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("CREATOR_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="No API key found"):
            load_creator_config()

    def test_loads_creator_vars(self, monkeypatch):
        monkeypatch.setenv("CREATOR_API_KEY", "creator-key")
        monkeypatch.setenv("CREATOR_BASE_URL", "http://creator-host")
        monkeypatch.setenv("CREATOR_MODEL", "gpt-4o")
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        config = load_creator_config()
        assert config.api_key == "creator-key"
        assert config.base_url == "http://creator-host"
        assert config.model == "gpt-4o"

    def test_falls_back_to_llm_vars(self, monkeypatch):
        monkeypatch.delenv("CREATOR_API_KEY", raising=False)
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
        monkeypatch.delenv("CREATOR_MODEL", raising=False)
        monkeypatch.setenv("LLM_API_KEY", "llm-key")
        monkeypatch.setenv("LLM_BASE_URL", "http://llm-host")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")

        config = load_creator_config()
        assert config.api_key == "llm-key"
        assert config.base_url == "http://llm-host"
        assert config.model == "gpt-4o"

    def test_creator_vars_take_precedence(self, monkeypatch):
        monkeypatch.setenv("CREATOR_API_KEY", "creator-key")
        monkeypatch.setenv("LLM_API_KEY", "llm-key")
        monkeypatch.setenv("CREATOR_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_MODEL", "other-model")
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)

        config = load_creator_config()
        assert config.api_key == "creator-key"
        assert config.model == "gpt-4o"

    def test_warns_on_small_model(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.delenv("CREATOR_API_KEY", raising=False)
        monkeypatch.delenv("CREATOR_MODEL", raising=False)
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_creator_config()
            assert len(w) == 1
            assert "7B gameplay model" in str(w[0].message)
            assert config.is_small_model is True

    def test_no_warning_for_large_model(self, monkeypatch):
        monkeypatch.setenv("CREATOR_API_KEY", "test-key")
        monkeypatch.setenv("CREATOR_MODEL", "gpt-4o")
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_creator_config()
            assert len(w) == 0
            assert config.is_small_model is False
