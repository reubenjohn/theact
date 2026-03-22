"""Extra tests for llm/config.py: settings.yaml-based config loading.

Covers the SETTINGS_FILE.exists() == True branch (lines 82-98) of
load_llm_config(), including API key from settings, env fallback, and
missing key error.
"""

import pytest

from theact.llm.config import load_llm_config


class TestLoadLLMConfigFromSettings:
    """Tests for the settings.yaml-based config path in load_llm_config()."""

    def test_loads_from_settings_yaml(self, tmp_path, monkeypatch):
        """When settings.yaml exists, all fields are loaded from it."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text(
            "llm_api_key: settings-key\n"
            "llm_base_url: https://settings.example.com/v1\n"
            "llm_model: settings-model\n"
            "llm_temperature: 0.7\n"
            "llm_max_tokens: 2000\n"
            "llm_context_limit: 16384\n"
        )
        # Patch SETTINGS_FILE in both modules (config imports from settings_store)
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        # Clear env vars to confirm we're reading from settings
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        config = load_llm_config()
        assert config.api_key == "settings-key"
        assert config.base_url == "https://settings.example.com/v1"
        assert config.model == "settings-model"
        assert config.default_temperature == 0.7
        assert config.default_max_tokens == 2000
        assert config.context_limit == 16384

    def test_settings_yaml_empty_key_falls_back_to_env(self, tmp_path, monkeypatch):
        """When settings.yaml has an empty API key, env var is used as fallback."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text(
            "llm_base_url: https://settings.example.com/v1\nllm_model: settings-model\n"
        )
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        monkeypatch.setenv("LLM_API_KEY", "env-fallback-key")

        config = load_llm_config()
        assert config.api_key == "env-fallback-key"
        assert config.base_url == "https://settings.example.com/v1"
        assert config.model == "settings-model"

    def test_settings_yaml_no_key_no_env_raises(self, tmp_path, monkeypatch):
        """When settings.yaml exists but has no key and env var is missing, raises."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text("llm_model: some-model\n")
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        with pytest.raises(ValueError, match="LLM_API_KEY not configured"):
            load_llm_config()

    def test_settings_yaml_key_in_yaml_overrides_env(self, tmp_path, monkeypatch):
        """API key from settings.yaml takes priority over env var."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text("llm_api_key: yaml-key\nllm_model: m\n")
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        monkeypatch.setenv("LLM_API_KEY", "env-key")

        config = load_llm_config()
        assert config.api_key == "yaml-key"
