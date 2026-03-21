# Step 05: Settings & Configuration

> **Implementation note:** This step adds a dedicated settings page at `/settings` where users can view and modify LLM configuration, creator model configuration, and display preferences from the web UI. Currently all configuration is done via environment variables in a `.env` file, requiring a manual edit and server restart to change anything. This step introduces a `settings.yaml` persistence layer that sits on top of `.env`, allowing web-configurable settings without touching secrets files. NiceGUI `password=True` inputs provide visual masking of API keys in the browser.

## 1. Overview

The web UI has no way to inspect or change configuration. Users must:
1. Stop the server
2. Edit `.env` with a text editor
3. Restart the server

This step adds:
- A new `/settings` page accessible from the menu and gameplay toolbar
- Form sections for LLM configuration, creator configuration, and display preferences
- A "Test Connection" button that verifies API credentials against the configured endpoint
- Persistence to a `settings.yaml` file in the project root, with `.env` as the fallback
- Immediate application of display preferences; LLM config changes take effect on the next session

## 2. Page Route

**Modified file:** `src/theact/web/app.py`

Register a new page route in `setup_app()`:

```python
@ui.page("/settings")
async def settings_page():
    """Settings page for LLM and display configuration."""
    from theact.web.settings import build_settings_page
    build_settings_page(on_back=lambda: ui.navigate.to("/"))
```

Add a navigation link to the settings page from two locations:

1. **Menu page** — Add a gear icon button in the banner area or footer:
   ```python
   ui.button(icon="settings", on_click=lambda: ui.navigate.to("/settings")).props(
       "flat dense"
   ).tooltip("Settings")
   ```

2. **Gameplay toolbar** (from Step 01) — Add a settings button:
   ```python
   ui.button(icon="settings", on_click=lambda: ui.navigate.to("/settings")).props(
       "flat dense"
   ).tooltip("Settings")
   ```

## 3. Settings Page Layout

**New file:** `src/theact/web/settings.py`

The settings page is organized into three card sections stacked vertically, each with a clear heading. A top bar provides navigation back to the menu and a "Save" button.

```python
"""Settings page: LLM configuration, creator config, and display preferences."""

from __future__ import annotations

import logging
from dataclasses import asdict

from nicegui import ui

from theact.io.settings_store import load_settings, save_settings, SettingsData

logger = logging.getLogger(__name__)


def build_settings_page(on_back: callable) -> None:
    """Build the full settings page."""
    settings = load_settings()

    with ui.column().classes("w-full max-w-3xl mx-auto p-4"):
        # --- Header bar ---
        with ui.row().classes("w-full items-center justify-between"):
            ui.button(icon="arrow_back", on_click=on_back).props("flat dense")
            ui.label("Settings").style(
                "font-size: 1.4em; font-weight: bold; color: #ccc;"
            )
            save_btn = ui.button("Save", icon="save").props("dense")

        ui.separator()

        # --- LLM Configuration ---
        llm_fields = _build_llm_section(settings)

        ui.separator()

        # --- Creator Configuration ---
        creator_fields = _build_creator_section(settings)

        ui.separator()

        # --- Display Preferences ---
        display_fields = _build_display_section(settings)

        # --- Save handler ---
        async def on_save():
            updated = _collect_form_values(llm_fields, creator_fields, display_fields)
            save_settings(updated)
            ui.notify(
                "Settings saved. LLM changes will take effect on next session.",
                type="positive",
            )

        save_btn.on_click(on_save)
```

## 4. LLM Configuration Section

This section controls the primary model used for gameplay (narrator, character, memory, game state, and summarizer agents).

```python
def _build_llm_section(settings: SettingsData) -> dict:
    """Build the LLM configuration card. Returns field references."""
    fields = {}

    with ui.card().classes("w-full"):
        ui.label("LLM Configuration").style(
            "font-size: 1.1em; font-weight: bold; color: #ccc;"
        )
        ui.label(
            "Primary model used for gameplay. Changes take effect on the next game session."
        ).style("color: #888; font-size: 0.85em;")

        # API Key — masked password input
        fields["api_key"] = (
            ui.input(
                label="API Key",
                value=settings.llm_api_key,
                password=True,
                password_toggle_button=True,
            )
            .classes("w-full")
            .props("outlined dense dark")
        )

        # Base URL — text input with preset dropdown
        preset_urls = {
            "OpenAI": "https://api.openai.com/v1",
            "OpenRouter": "https://openrouter.ai/api/v1",
            "Together AI": "https://api.together.xyz/v1",
            "Groq": "https://api.groq.com/openai/v1",
            "Ollama (local)": "http://localhost:11434/v1",
        }

        with ui.row().classes("w-full items-end gap-2"):
            fields["base_url"] = (
                ui.input(
                    label="Base URL",
                    value=settings.llm_base_url,
                )
                .classes("flex-grow")
                .props("outlined dense dark")
            )

            def make_preset_handler(url_field, url: str):
                def handler():
                    url_field.value = url
                return handler

            with ui.button(icon="expand_more").props("flat dense"):
                with ui.menu():
                    for name, url in preset_urls.items():
                        ui.menu_item(
                            name,
                            on_click=make_preset_handler(fields["base_url"], url),
                        )

        # Model name — freeform text (model names vary by provider)
        fields["model"] = (
            ui.input(
                label="Model",
                value=settings.llm_model,
                placeholder="e.g. qwen/qwen3-8b, gpt-4o-mini",
            )
            .classes("w-full")
            .props("outlined dense dark")
        )

        # Temperature — slider
        ui.label("Temperature").style("color: #aaa; font-size: 0.85em; margin-top: 8px;")
        fields["temperature"] = ui.slider(
            min=0.0, max=2.0, step=0.1, value=settings.llm_temperature
        ).props("label-always")

        # Max Tokens — number input
        fields["max_tokens"] = (
            ui.number(
                label="Default Max Tokens",
                value=settings.llm_max_tokens,
                min=256,
                max=8192,
                step=64,
            )
            .classes("w-full")
            .props("outlined dense dark")
        )

        # Context Limit — number input
        fields["context_limit"] = (
            ui.number(
                label="Context Limit",
                value=settings.llm_context_limit,
                min=2048,
                max=131072,
                step=1024,
            )
            .classes("w-full")
            .props("outlined dense dark")
        )

        # Test Connection button
        with ui.row().classes("items-center gap-2 mt-2"):
            test_btn = ui.button("Test Connection", icon="network_check").props("dense")
            test_status = ui.label("").style("font-size: 0.85em;")

            async def on_test():
                test_status.text = "Testing..."
                test_status.style("color: #aaa;")
                try:
                    from theact.io.settings_store import test_llm_connection

                    ok, msg = await test_llm_connection(
                        api_key=fields["api_key"].value,
                        base_url=fields["base_url"].value,
                        model=fields["model"].value,
                    )
                    if ok:
                        test_status.text = f"Connected: {msg}"
                        test_status.style("color: #69f0ae;")
                    else:
                        test_status.text = f"Failed: {msg}"
                        test_status.style("color: #ff5252;")
                except Exception as e:
                    test_status.text = f"Error: {e}"
                    test_status.style("color: #ff5252;")

            test_btn.on_click(on_test)

    return fields
```

The "Test Connection" button makes a minimal API call (e.g., a one-token completion or a `models.list()` request) to verify that the provided API key, base URL, and model are valid. The API call itself runs server-side.

## 5. Creator Configuration Section

The creator agent (game creation wizard) can use a different, larger model. This section mirrors the LLM section but with separate fields.

```python
def _build_creator_section(settings: SettingsData) -> dict:
    """Build the creator model configuration card."""
    fields = {}

    with ui.card().classes("w-full"):
        ui.label("Creator Configuration").style(
            "font-size: 1.1em; font-weight: bold; color: #ccc;"
        )
        ui.label(
            "Model used for game creation. A larger, more capable model is recommended."
        ).style("color: #888; font-size: 0.85em;")

        # "Use same config as gameplay" checkbox
        fields["use_same"] = ui.checkbox(
            "Use same config as gameplay",
            value=settings.creator_use_same,
        )

        # Creator-specific fields (disabled when use_same is checked)
        fields["api_key"] = (
            ui.input(
                label="Creator API Key",
                value=settings.creator_api_key,
                password=True,
                password_toggle_button=True,
            )
            .classes("w-full")
            .props("outlined dense dark")
            .bind_enabled_from(fields["use_same"], "value", backward=lambda v: not v)
        )

        fields["base_url"] = (
            ui.input(
                label="Creator Base URL",
                value=settings.creator_base_url,
            )
            .classes("w-full")
            .props("outlined dense dark")
            .bind_enabled_from(fields["use_same"], "value", backward=lambda v: not v)
        )

        fields["model"] = (
            ui.input(
                label="Creator Model",
                value=settings.creator_model,
                placeholder="e.g. claude-sonnet-4-20250514, gpt-4o",
            )
            .classes("w-full")
            .props("outlined dense dark")
            .bind_enabled_from(fields["use_same"], "value", backward=lambda v: not v)
        )

    return fields
```

When "Use same config as gameplay" is checked, the creator fields are visually disabled. On save, if this checkbox is active, the creator fields are omitted from `settings.yaml` so that `load_llm_config()` falls through to the primary LLM values.

## 6. Display Preferences Section

Display preferences control the web UI's visual behavior and apply immediately (no restart needed).

```python
def _build_display_section(settings: SettingsData) -> dict:
    """Build the display preferences card."""
    fields = {}

    with ui.card().classes("w-full"):
        ui.label("Display Preferences").style(
            "font-size: 1.1em; font-weight: bold; color: #ccc;"
        )

        # Default thinking toggle — sets initial state for new sessions
        fields["show_thinking"] = ui.switch(
            "Show model thinking by default",
            value=settings.default_show_thinking,
        )

        # Chat font size
        ui.label("Chat Font Size").style(
            "color: #aaa; font-size: 0.85em; margin-top: 8px;"
        )
        fields["font_size"] = ui.toggle(
            {
                "small": "Small",
                "medium": "Medium",
                "large": "Large",
            },
            value=settings.font_size,
        )

        # Message density
        ui.label("Message Density").style(
            "color: #aaa; font-size: 0.85em; margin-top: 8px;"
        )
        fields["density"] = ui.toggle(
            {
                "compact": "Compact",
                "comfortable": "Comfortable",
            },
            value=settings.density,
        )

    return fields
```

Display preferences are stored in `settings.yaml` and loaded by the gameplay session to set CSS classes on the chat container:

| Preference | `small` | `medium` | `large` |
|---|---|---|---|
| Font size | `text-sm` (14px) | `text-base` (16px) | `text-lg` (18px) |

| Preference | `compact` | `comfortable` |
|---|---|---|
| Message spacing | `gap-1 py-1` | `gap-3 py-2` |

## 7. Persistence Strategy

**New file:** `src/theact/io/settings_store.py`

> **Note:** `settings_store.py` lives in `src/theact/io/` (not `src/theact/web/`) so that both `load_llm_config()` in `src/theact/llm/config.py` and the web settings page can import from it without creating a core-to-web dependency. The web layer imports from `io`; the `io` layer never imports from `web`.

Two persistence layers are available:

- **Option A:** Write directly to `.env` — simple but mixes web-configurable settings with hand-edited secrets, requires restart, and risks corrupting the file.
- **Option B:** Write to a separate `settings.yaml` in the project root — clean separation, no restart needed for display preferences, `.env` remains the source of truth for secrets.

**Recommendation: Option B.** Use `settings.yaml` for web-configurable settings, with `.env` as the fallback for values not set in `settings.yaml`.

**Implementation step:** Add `settings.yaml` to the project's `.gitignore` file, since it may contain API keys:
```
# Web UI settings (may contain API keys)
settings.yaml
```

**Load order:** `.env` values (via `os.environ`) -> `settings.yaml` overrides -> runtime state

```python
"""Settings persistence: load/save web-configurable settings to settings.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

SETTINGS_FILE = Path("settings.yaml")  # See note below about path resolution
```

> **Note:** `Path("settings.yaml")` resolves relative to the current working directory, which may vary depending on how the server is launched. During implementation, use the same data directory resolution strategy as `save_manager.py` (e.g., resolving relative to the project root) to ensure `settings.yaml` is always found in a predictable location.

```python
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
    font_size: str = "medium"      # small | medium | large
    density: str = "comfortable"   # compact | comfortable


def load_settings() -> SettingsData:
    """Load settings from settings.yaml, falling back to env vars.

    Priority: settings.yaml value > env var > dataclass default.
    """
    settings = SettingsData()

    # Layer 1: env vars (from .env via dotenv)
    settings.llm_api_key = os.environ.get("LLM_API_KEY", settings.llm_api_key)
    settings.llm_base_url = os.environ.get("LLM_BASE_URL", settings.llm_base_url)
    settings.llm_model = os.environ.get("LLM_MODEL", settings.llm_model)
    settings.creator_api_key = os.environ.get("CREATOR_API_KEY", settings.creator_api_key)
    settings.creator_base_url = os.environ.get("CREATOR_BASE_URL", settings.creator_base_url)
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
    The .env file is NOT modified.
    """
    data = asdict(settings)
    # Remove empty API keys so env vars remain the fallback
    if not data.get("llm_api_key"):
        data.pop("llm_api_key", None)
    if not data.get("creator_api_key"):
        data.pop("creator_api_key", None)

    SETTINGS_FILE.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


async def test_llm_connection(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    """Test LLM connection by listing models or making a minimal completion.

    Returns (success: bool, message: str).
    """
    from openai import AsyncOpenAI

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        # Try listing models first (lightweight, no tokens consumed)
        models = await client.models.list()
        model_ids = [m.id for m in models.data[:5]]
        return True, f"{len(models.data)} models available"
    except Exception as e:
        # Fall back to a minimal completion to test auth
        try:
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1,
            )
            return True, f"Model {model} responded"
        except Exception as e2:
            return False, str(e2)
```

**Updating `load_llm_config()`:**

**Modified file:** `src/theact/llm/config.py`

Update `load_llm_config()` to check `settings.yaml` before env vars:

```python
def load_llm_config() -> LLMConfig:
    """Load LLM configuration from settings.yaml, falling back to env vars."""
    from theact.io.settings_store import load_settings, SETTINGS_FILE

    # If settings.yaml exists, use it as the primary source
    if SETTINGS_FILE.exists():
        settings = load_settings()
        api_key = settings.llm_api_key
        if not api_key:
            api_key = os.environ.get("LLM_API_KEY", "")
        if not api_key:
            raise ValueError(
                "LLM_API_KEY not configured. "
                "Set it in Settings or in your .env file."
            )
        return LLMConfig(
            base_url=settings.llm_base_url,
            api_key=api_key,
            model=settings.llm_model,
            default_temperature=settings.llm_temperature,
            default_max_tokens=settings.llm_max_tokens,
            context_limit=settings.llm_context_limit,
        )

    # Original env-var-only path (unchanged)
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise ValueError(
            "LLM_API_KEY environment variable is required. "
            "Set it in your .env file or shell environment."
        )
    return LLMConfig(
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.environ.get("LLM_MODEL", ""),
    )
```

This preserves full backward compatibility — if `settings.yaml` does not exist, behavior is identical to the current implementation.

**Updating `load_creator_config()`:**

**Modified file:** `src/theact/creator/config.py`

`load_creator_config()` must also be updated to check `settings.yaml` before falling back to env vars, mirroring the `load_llm_config()` pattern above. When `settings.yaml` exists and `creator_use_same` is `False`, use the creator-specific fields (`creator_api_key`, `creator_base_url`, `creator_model`). When `creator_use_same` is `True` or the creator fields are empty, fall through to the primary LLM values. If `settings.yaml` does not exist, the existing env-var-only path is unchanged.

## 8. Applying Settings

Settings fall into two categories based on when they take effect:

| Category | When applied | Examples |
|---|---|---|
| **Immediate** | On save, current page updates | Display preferences (font size, density, thinking toggle) |
| **Next session** | When a new game session starts or page reloads | LLM config (API key, base URL, model, temperature, max tokens, context limit) |

**Save flow:**

1. User clicks "Save"
2. `_collect_form_values()` reads all form fields into a `SettingsData` instance. This function must be implemented to read `.value` from each NiceGUI field reference in `llm_fields`, `creator_fields`, and `display_fields`, and construct a `SettingsData` instance from them. It is not defined in the code samples above and must be added during implementation.
3. `save_settings()` writes to `settings.yaml`
4. `ui.notify("Settings saved. LLM changes will take effect on next session.", type="positive")`
5. Display preferences are applied to `app.storage.tab` so they persist for the current browser tab and are read by `GameplaySession` on next build

**LLM config is NOT hot-reloaded** into an active gameplay session. The `LLMConfig` instance is created once when the gameplay page loads (in `app.py`'s `index()` handler) and passed to `GameplaySession`. Changing LLM settings mid-game requires returning to the menu and re-entering gameplay.

## 9. Security Considerations

API keys are sensitive credentials. The settings page must handle them carefully:

1. **Masked display.** API key inputs use `password=True` with `password_toggle_button=True`. The key is visually masked by default.

2. **Keys are transmitted to the browser.** NiceGUI uses WebSocket-based bidirectional binding — form field values (including API keys) ARE sent to the browser for rendering. The `password=True` flag provides visual masking only (the input displays dots instead of text), not data isolation. The key value is present in WebSocket messages and accessible in browser dev tools. This is acceptable because the web UI is designed for single-user local use, not as a multi-tenant service.

3. **No logging.** Never log API key values. The `save_settings()` function writes to `settings.yaml` but does not log the contents.

4. **File permissions.** `settings.yaml` is written with default file permissions. On multi-user systems, the server operator should restrict permissions. This is documented but not enforced by code (the web UI is designed for single-user local use).

5. **No browser-side API calls.** The "Test Connection" button runs the API call server-side via an async NiceGUI event handler. The API key is not used in any client-side JavaScript.

## 10. Tests

**New file:** `tests/web/test_settings.py`

All tests use the Playwright-based browser testing pattern from the existing web test suite (`tests/web/conftest.py`): synchronous `def` tests, `web_server` fixture, and `playwright.sync_api`.

```python
"""Tests for the settings page."""

from playwright.sync_api import expect


def test_settings_page_accessible(page, web_server):
    """Settings page loads at /settings."""
    page.goto(f"{web_server}/settings")
    expect(page.get_by_text("Settings")).to_be_visible()


def test_settings_back_button(page, web_server):
    """Back button navigates to the menu."""
    page.goto(f"{web_server}/settings")
    page.locator("button:has(i:text('arrow_back'))").click()
    expect(page).to_have_url(f"{web_server}/")


def test_llm_config_fields_present(page, web_server):
    """LLM configuration section has all expected fields."""
    page.goto(f"{web_server}/settings")
    expect(page.get_by_text("LLM Configuration")).to_be_visible()
    expect(page.get_by_label("API Key")).to_be_visible()
    expect(page.get_by_label("Base URL")).to_be_visible()
    expect(page.get_by_label("Model")).to_be_visible()
    expect(page.get_by_text("Temperature")).to_be_visible()
    expect(page.get_by_label("Default Max Tokens")).to_be_visible()
    expect(page.get_by_label("Context Limit")).to_be_visible()


def test_api_key_masked_by_default(page, web_server):
    """API key input is a password field (masked)."""
    page.goto(f"{web_server}/settings")
    api_key_input = page.locator("input[type='password']").first
    expect(api_key_input).to_be_visible()


def test_test_connection_button_exists(page, web_server):
    """Test Connection button is present."""
    page.goto(f"{web_server}/settings")
    expect(page.get_by_text("Test Connection")).to_be_visible()


def test_creator_config_section_present(page, web_server):
    """Creator configuration section has separate fields."""
    page.goto(f"{web_server}/settings")
    expect(page.get_by_text("Creator Configuration")).to_be_visible()
    expect(page.get_by_text("Use same config as gameplay")).to_be_visible()


def test_display_preferences_present(page, web_server):
    """Display preferences section has expected controls."""
    page.goto(f"{web_server}/settings")
    expect(page.get_by_text("Display Preferences")).to_be_visible()
    expect(page.get_by_text("Show model thinking by default")).to_be_visible()
    expect(page.get_by_text("Chat Font Size")).to_be_visible()
    expect(page.get_by_text("Message Density")).to_be_visible()


def test_save_button_exists(page, web_server):
    """Save button is present in the header bar."""
    page.goto(f"{web_server}/settings")
    expect(page.get_by_text("Save")).to_be_visible()


def test_menu_has_settings_link(page, web_server):
    """Menu page has a settings navigation button."""
    page.goto(f"{web_server}/")
    settings_btn = page.locator("[aria-label='Settings']")
    expect(settings_btn).to_be_visible()
    settings_btn.click()
    expect(page).to_have_url(f"{web_server}/settings")
```

Additional unit tests (no browser needed) for the persistence layer:

**New file:** `tests/web/test_settings_store.py`

```python
"""Unit tests for settings persistence (no browser required)."""

from theact.io.settings_store import SettingsData, load_settings, save_settings


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    """Settings survive a save/load cycle."""
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("theact.io.settings_store.SETTINGS_FILE", settings_file)

    original = SettingsData(
        llm_base_url="https://api.example.com/v1",
        llm_model="test-model",
        llm_temperature=0.7,
        font_size="large",
        density="compact",
    )
    save_settings(original)

    loaded = load_settings()
    assert loaded.llm_base_url == "https://api.example.com/v1"
    assert loaded.llm_model == "test-model"
    assert loaded.llm_temperature == 0.7
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
```

## 11. What This Step Does NOT Do

- **Hot-reload LLM config into active sessions.** Changing the model mid-game requires returning to the menu. The `LLMConfig` passed to `GameplaySession` is immutable for the session's lifetime.
- **Per-agent config overrides from the UI.** The `AgentLLMConfig` values (`NARRATOR_CONFIG`, `CHARACTER_CONFIG`, etc.) are not exposed in the settings page. They are code-level tuning knobs for developers, not end-user settings.
- **Authentication or access control.** The settings page is accessible to anyone who can reach the web UI. There is no password gate. The web UI is designed for single-user local use.
- **Import/export settings.** No button to download `settings.yaml` or upload a replacement. Users who need this can manually copy the file.
- **Model picker with live model list.** The model field is freeform text. A future enhancement could query the API's `/models` endpoint and populate a dropdown, but this is unreliable across providers.
- **Proxy or network configuration.** HTTP proxy settings, timeouts, and retry policies are not configurable from the UI.
- **Theme or color scheme selection.** The dark theme is hardcoded. A light/dark toggle is out of scope for this step.

## 12. Verification

After implementation, confirm:

1. **Settings page accessible from menu.** The gear icon or "Settings" link on the main menu page navigates to `/settings`. The page loads without errors.
2. **Settings page accessible from gameplay.** The toolbar settings button (from Step 01) navigates to `/settings`. Pressing back returns to gameplay.
3. **LLM configuration form shows current values.** If `.env` has `LLM_BASE_URL=https://api.openai.com/v1` and `LLM_MODEL=gpt-4o-mini`, those values appear in the form fields on first load.
4. **API key is masked by default.** The API key field shows asterisks. Clicking the reveal toggle shows the actual key. Re-clicking hides it.
5. **Base URL presets work.** Clicking the dropdown next to Base URL and selecting "Groq" fills in `https://api.groq.com/openai/v1`.
6. **"Test Connection" verifies credentials.** With valid credentials, shows a green success message. With an invalid key, shows a red error message. The button shows "Testing..." while the request is in flight.
7. **Creator config section shows separate fields.** Checking "Use same config as gameplay" disables the creator-specific fields. Unchecking re-enables them.
8. **Saving persists to `settings.yaml`.** After clicking Save, a `settings.yaml` file exists in the project root with the configured values. API keys are present in the file only if explicitly set (not empty).
9. **`.env` is not modified.** The `.env` file is unchanged after saving settings.
10. **Display preferences apply immediately.** Changing font size to "large" and saving, then navigating to gameplay, shows larger chat text. Changing density to "compact" reduces spacing between messages.
11. **LLM config applies on next session.** Changing the model in settings, saving, returning to the menu, and starting a new game uses the new model. The old game session (if still open in another tab) continues with the old model.
12. **`settings.yaml` is gitignored.** Running `git status` after saving settings does not show `settings.yaml` as an untracked file.
13. **Navigation works.** Back button from settings returns to the menu. Menu link goes to settings. Round-trip navigation is smooth with no blank screens or errors.
14. **Existing tests pass.** All tests in `tests/web/` continue to pass. The `load_llm_config()` change is backward-compatible — when `settings.yaml` does not exist, behavior is identical to before.
