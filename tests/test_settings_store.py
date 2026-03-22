"""Unit tests for settings persistence (no browser required)."""

from theact.io.settings_store import SettingsData, load_settings, save_settings


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    """Settings survive a save/load cycle."""
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)

    # Clear env vars that would interfere
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("CREATOR_API_KEY", raising=False)
    monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
    monkeypatch.delenv("CREATOR_MODEL", raising=False)

    original = SettingsData(
        llm_api_key="test-key",
        llm_base_url="https://api.example.com/v1",
        llm_model="test-model",
        llm_temperature=0.7,
        llm_max_tokens=2000,
        llm_context_limit=16384,
        font_size="large",
        density="compact",
    )
    save_settings(original)

    loaded = load_settings()
    assert loaded.llm_api_key == "test-key"
    assert loaded.llm_base_url == "https://api.example.com/v1"
    assert loaded.llm_model == "test-model"
    assert loaded.llm_temperature == 0.7
    assert loaded.llm_max_tokens == 2000
    assert loaded.llm_context_limit == 16384
    assert loaded.font_size == "large"
    assert loaded.density == "compact"


def test_env_var_fallback(tmp_path, monkeypatch):
    """When settings.yaml doesn't exist, env vars are used."""
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
    monkeypatch.setenv("LLM_API_KEY", "test-key-123")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    loaded = load_settings()
    assert loaded.llm_api_key == "test-key-123"
    assert loaded.llm_model == "env-model"


def test_settings_yaml_overrides_env(tmp_path, monkeypatch):
    """settings.yaml values take priority over env vars."""
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
    monkeypatch.setenv("LLM_MODEL", "env-model")

    original = SettingsData(llm_model="yaml-model")
    save_settings(original)

    loaded = load_settings()
    assert loaded.llm_model == "yaml-model"


def test_empty_api_key_not_persisted(tmp_path, monkeypatch):
    """Empty API keys are omitted from settings.yaml so env vars can fill them."""
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)

    original = SettingsData(llm_api_key="", llm_model="test-model")
    save_settings(original)

    raw = settings_file.read_text()
    assert "llm_api_key" not in raw


def test_creator_fields_persisted(tmp_path, monkeypatch):
    """Creator-specific fields are saved and loaded correctly."""
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
    monkeypatch.delenv("CREATOR_API_KEY", raising=False)
    monkeypatch.delenv("CREATOR_BASE_URL", raising=False)
    monkeypatch.delenv("CREATOR_MODEL", raising=False)

    original = SettingsData(
        creator_use_same=False,
        creator_api_key="creator-key",
        creator_base_url="https://creator.example.com/v1",
        creator_model="big-model",
    )
    save_settings(original)

    loaded = load_settings()
    assert loaded.creator_use_same is False
    assert loaded.creator_api_key == "creator-key"
    assert loaded.creator_base_url == "https://creator.example.com/v1"
    assert loaded.creator_model == "big-model"


def test_display_preferences_defaults(tmp_path, monkeypatch):
    """Default display preferences are correct when nothing is set."""
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    loaded = load_settings()
    assert loaded.default_show_thinking is False
    assert loaded.font_size == "medium"
    assert loaded.density == "comfortable"
    assert loaded.debug_mode is False


def test_debug_mode_persisted(tmp_path, monkeypatch):
    """debug_mode survives a save/load cycle."""
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    original = SettingsData(debug_mode=True)
    save_settings(original)

    loaded = load_settings()
    assert loaded.debug_mode is True
