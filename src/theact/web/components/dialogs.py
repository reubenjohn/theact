"""Reusable dialog builders for the web UI."""

from __future__ import annotations

from typing import Awaitable, Callable

from nicegui import ui


def confirm_dialog(
    title: str,
    message: str,
    on_confirm: Callable[[], None] | Callable[[], Awaitable[None]],
    confirm_text: str = "Confirm",
    confirm_color: str = "#ff9800",
) -> None:
    """Show a confirmation dialog with Cancel and Confirm buttons."""
    with ui.dialog() as dialog, ui.card():
        ui.label(title).style("font-weight: bold; color: #ccc;")
        ui.label(message).style("color: #999;")
        with ui.row().classes("justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def _confirm():
                dialog.close()
                result = on_confirm()
                if hasattr(result, "__await__"):
                    await result

            ui.button(confirm_text, on_click=_confirm).props("flat").style(
                f"color: {confirm_color};"
            )
    dialog.open()


def text_input_dialog(
    title: str,
    message: str,
    on_submit: Callable[[str], None] | Callable[[str], Awaitable[None]],
    label: str = "Name",
    placeholder: str = "",
    submit_text: str = "Create",
    submit_color: str = "#69f0ae",
) -> None:
    """Show a dialog with a text input field."""
    with ui.dialog() as dialog, ui.card():
        ui.label(title).style("font-weight: bold; color: #ccc;")
        ui.label(message).style("color: #999;")
        name_input = (
            ui.input(label=label, placeholder=placeholder)
            .props("outlined dense dark")
            .classes("w-full")
        )
        with ui.row().classes("justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def _submit():
                name = (name_input.value or "").strip()
                if not name:
                    ui.notify(f"Please enter a {label.lower()}.", type="warning")
                    return
                dialog.close()
                result = on_submit(name)
                if hasattr(result, "__await__"):
                    await result

            ui.button(submit_text, on_click=_submit).props("flat").style(
                f"color: {submit_color};"
            )
    dialog.open()


def number_input_dialog(
    title: str,
    message: str,
    on_submit: Callable[[int], None] | Callable[[int], Awaitable[None]],
    label: str = "Value",
    default: int = 1,
    min_val: int = 1,
    max_val: int = 100,
    submit_text: str = "Confirm",
    submit_color: str = "#ff9800",
) -> None:
    """Show a dialog with a number input field."""
    with ui.dialog() as dialog, ui.card():
        ui.label(title).style("font-weight: bold; color: #ccc;")
        ui.label(message).style("color: #999;")
        num_input = (
            ui.number(label=label, value=default, min=min_val, max=max_val)
            .props("outlined dense dark")
            .style("width: 100px;")
        )
        with ui.row().classes("justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def _submit():
                value = int(num_input.value or default)
                dialog.close()
                result = on_submit(value)
                if hasattr(result, "__await__"):
                    await result

            ui.button(submit_text, on_click=_submit).props("flat").style(
                f"color: {submit_color};"
            )
    dialog.open()
