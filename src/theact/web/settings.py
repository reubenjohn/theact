"""Settings page: LLM configuration, creator config, and display preferences."""

from __future__ import annotations

import logging

from nicegui import ui

from theact.io.settings_store import SettingsData, load_settings, save_settings

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


def _build_llm_section(settings: SettingsData) -> dict:
    """Build the LLM configuration card. Returns field references."""
    fields = {}

    with ui.card().classes("w-full"):
        ui.label("LLM Configuration").style(
            "font-size: 1.1em; font-weight: bold; color: #ccc;"
        )
        ui.label(
            "Primary model used for gameplay. "
            "Changes take effect on the next game session."
        ).style("color: #888; font-size: 0.85em;")

        # API Key -- masked password input
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

        # Base URL -- text input with preset dropdown
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

        # Model name
        fields["model"] = (
            ui.input(
                label="Model",
                value=settings.llm_model,
                placeholder="e.g. qwen/qwen3-8b, gpt-4o-mini",
            )
            .classes("w-full")
            .props("outlined dense dark")
        )

        # Temperature -- slider
        ui.label("Temperature").style(
            "color: #aaa; font-size: 0.85em; margin-top: 8px;"
        )
        fields["temperature"] = ui.slider(
            min=0.0, max=2.0, step=0.1, value=settings.llm_temperature
        ).props("label-always")

        # Max Tokens -- number input
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

        # Context Limit -- number input
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


def _build_display_section(settings: SettingsData) -> dict:
    """Build the display preferences card."""
    fields = {}

    with ui.card().classes("w-full"):
        ui.label("Display Preferences").style(
            "font-size: 1.1em; font-weight: bold; color: #ccc;"
        )

        # Default thinking toggle
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

        ui.separator()

        # Debug / diagnostics
        fields["debug_mode"] = ui.switch(
            "Write diagnostics each turn",
            value=settings.debug_mode,
        )
        ui.label(
            "Writes per-agent prompts, responses, and parsed output "
            "to diagnostics/turn-NNN/ in the save directory."
        ).style("color: #888; font-size: 0.8em;")

    return fields


def _collect_form_values(
    llm_fields: dict, creator_fields: dict, display_fields: dict
) -> SettingsData:
    """Read all form fields and construct a SettingsData instance."""
    return SettingsData(
        llm_api_key=llm_fields["api_key"].value or "",
        llm_base_url=llm_fields["base_url"].value or "",
        llm_model=llm_fields["model"].value or "",
        llm_temperature=float(llm_fields["temperature"].value),
        llm_max_tokens=int(llm_fields["max_tokens"].value or 1500),
        llm_context_limit=int(llm_fields["context_limit"].value or 8192),
        creator_use_same=creator_fields["use_same"].value,
        creator_api_key=creator_fields["api_key"].value or "",
        creator_base_url=creator_fields["base_url"].value or "",
        creator_model=creator_fields["model"].value or "",
        default_show_thinking=display_fields["show_thinking"].value,
        font_size=display_fields["font_size"].value or "medium",
        density=display_fields["density"].value or "comfortable",
        debug_mode=display_fields["debug_mode"].value,
    )
