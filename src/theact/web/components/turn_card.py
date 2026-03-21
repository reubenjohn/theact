"""Turn card creation for the gameplay view."""

from __future__ import annotations

from nicegui import ui

from theact.web.styles import MOOD_COLOR


def create_turn_card(
    container: ui.element, turn_number: int, chapter_title: str
) -> ui.card:
    """Create a card element for a single turn."""
    with container:
        card = ui.card().classes("w-full")
        with card:
            ui.label(f"Turn {turn_number} -- {chapter_title}").style(
                "color: #888; font-size: 0.8em; margin-bottom: 8px;"
            )
    return card


def create_turn_info_bar(
    container: ui.element,
    mood: str | None,
    beats_hit: list[str],
    chapter_advanced: bool,
    new_chapter: str | None,
) -> None:
    """Render a color-coded turn info line inside a turn card.

    Args:
        container: The turn card element to append into.
        mood: Narrator mood string, or None.
        beats_hit: List of beat descriptions hit this turn.
        chapter_advanced: Whether the chapter advanced.
        new_chapter: New chapter ID if chapter_advanced is True.
    """
    has_content = mood or beats_hit or chapter_advanced
    if not has_content:
        return

    with container:
        with (
            ui.row()
            .classes("w-full items-center gap-3 mt-2")
            .style("border-top: 1px solid #333; padding-top: 6px;")
        ):
            if mood:
                ui.label(f"Mood: {mood}").style(
                    f"color: {MOOD_COLOR}; font-size: 0.75em; font-style: italic;"
                )

            if beats_hit:
                for beat in beats_hit:
                    ui.badge(beat, color="green").props("outline").style(
                        "font-size: 0.7em;"
                    )

            if chapter_advanced and new_chapter:
                ui.badge(f"Chapter: {new_chapter}", color="amber").props(
                    "outline"
                ).style("font-size: 0.7em;")
