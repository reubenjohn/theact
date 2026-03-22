"""Extra tests for settings_store: YAML loop, test_llm_connection paths.

Covers:
- load_settings() YAML iteration loop (lines 81-85)
- test_llm_connection() success via models.list
- test_llm_connection() fallback when models.list fails
- test_llm_connection() both paths fail (re-raises)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theact.io.settings_store import (
    load_settings,
    test_llm_connection as check_llm_connection,
)


# ------------------------------------------------------------------
# load_settings(): YAML iteration loop (lines 81-85)
# ------------------------------------------------------------------


class TestLoadSettingsYAMLLoop:
    def test_load_from_yaml_file(self, tmp_path, monkeypatch):
        """Verify the YAML loop sets each known attribute on SettingsData."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text(
            "llm_model: my-model\n"
            "llm_temperature: 0.5\n"
            "font_size: large\n"
            "debug_mode: true\n"
        )
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        loaded = load_settings()
        assert loaded.llm_model == "my-model"
        assert loaded.llm_temperature == 0.5
        assert loaded.font_size == "large"
        assert loaded.debug_mode is True

    def test_unknown_yaml_keys_ignored(self, tmp_path, monkeypatch):
        """Unknown keys in YAML are silently ignored (hasattr guard)."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text(
            "llm_model: valid-model\nunknown_future_key: some-value\n"
        )
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        loaded = load_settings()
        assert loaded.llm_model == "valid-model"
        assert not hasattr(loaded, "unknown_future_key")

    def test_corrupt_yaml_falls_back(self, tmp_path, monkeypatch):
        """When YAML is corrupt, logger.warning fires and defaults are used."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text(": : : bad yaml [[[")
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        loaded = load_settings()
        # Should still return defaults, not crash
        assert loaded.llm_model == ""
        assert loaded.llm_temperature == 1.0

    def test_empty_yaml_file(self, tmp_path, monkeypatch):
        """Empty YAML file (safe_load returns None) should use defaults."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text("")
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        loaded = load_settings()
        assert loaded.llm_model == ""

    def test_yaml_overrides_env_vars(self, tmp_path, monkeypatch):
        """YAML values take precedence over environment variables."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text("llm_api_key: yaml-key\nllm_model: yaml-model\n")
        monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
        monkeypatch.setenv("LLM_API_KEY", "env-key")
        monkeypatch.setenv("LLM_MODEL", "env-model")

        loaded = load_settings()
        # YAML layer overwrites the env-var layer
        assert loaded.llm_api_key == "yaml-key"
        assert loaded.llm_model == "yaml-model"


# ------------------------------------------------------------------
# test_llm_connection(): success via models.list (lines 119-121)
# ------------------------------------------------------------------


class TestLLMConnectionSuccess:
    @pytest.mark.asyncio
    async def test_models_list_success(self):
        """When models.list() succeeds, returns True with model count."""
        mock_models_response = MagicMock()
        mock_models_response.data = [MagicMock(), MagicMock(), MagicMock()]

        mock_client = AsyncMock()
        mock_client.models.list = AsyncMock(return_value=mock_models_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            success, message = await check_llm_connection(
                api_key="test-key",
                base_url="https://api.example.com/v1",
                model="test-model",
            )

        assert success is True
        assert "3 models available" in message


# ------------------------------------------------------------------
# test_llm_connection(): fallback path (lines 124-131)
# ------------------------------------------------------------------


class TestLLMConnectionFallback:
    @pytest.mark.asyncio
    async def test_models_list_fails_completion_succeeds(self):
        """When models.list fails, fallback to a minimal completion."""
        mock_client_fail = AsyncMock()
        mock_client_fail.models.list = AsyncMock(
            side_effect=Exception("models.list not supported")
        )

        mock_client_ok = AsyncMock()
        mock_client_ok.chat.completions.create = AsyncMock(return_value=MagicMock())

        # First call (for models.list) raises; second call (for completion) succeeds
        clients = [mock_client_fail, mock_client_ok]
        call_count = {"n": 0}

        def make_client(**kwargs):
            idx = call_count["n"]
            call_count["n"] += 1
            return clients[idx]

        with patch("openai.AsyncOpenAI", side_effect=make_client):
            success, message = await check_llm_connection(
                api_key="test-key",
                base_url="https://api.example.com/v1",
                model="fallback-model",
            )

        assert success is True
        assert "fallback-model responded" in message


# ------------------------------------------------------------------
# test_llm_connection(): both paths fail (lines 132-133)
# ------------------------------------------------------------------


class TestLLMConnectionBothFail:
    @pytest.mark.asyncio
    async def test_both_fail_returns_error(self):
        """When both models.list and completion fail, returns False with error."""
        mock_client_1 = AsyncMock()
        mock_client_1.models.list = AsyncMock(side_effect=Exception("auth failed"))

        mock_client_2 = AsyncMock()
        mock_client_2.chat.completions.create = AsyncMock(
            side_effect=Exception("connection refused")
        )

        clients = [mock_client_1, mock_client_2]
        call_count = {"n": 0}

        def make_client(**kwargs):
            idx = call_count["n"]
            call_count["n"] += 1
            return clients[idx]

        with patch("openai.AsyncOpenAI", side_effect=make_client):
            success, message = await check_llm_connection(
                api_key="bad-key",
                base_url="https://api.example.com/v1",
                model="any-model",
            )

        assert success is False
        assert "connection refused" in message
