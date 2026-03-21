"""Shared HTML utilities for the web UI."""

from __future__ import annotations

import html as html_lib
import time

from nicegui import ui

from theact.commands.types import CommandResult


def escape_html(text: str) -> str:
    """Escape HTML entities in text."""
    return html_lib.escape(text)


def text_to_html(text: str, color: str = "#e0e0e0") -> str:
    """Convert plain text to safe HTML."""
    escaped = escape_html(text)
    formatted = escaped.replace("\n", "<br>")
    return f'<div style="color: {color}; white-space: pre-wrap;">{formatted}</div>'


def render_table_html(
    rows: list[dict[str, str]], columns: list[str] | None = None
) -> str:
    """Render a list of dicts as an HTML table string."""
    if not rows:
        return ""
    if columns is None:
        columns = list(rows[0].keys())

    header = "".join(
        f'<th style="text-align: left; padding: 4px; border-bottom: 1px solid #555;">'
        f"{escape_html(col)}</th>"
        for col in columns
    )
    body = ""
    for row in rows:
        cells = "".join(
            f'<td style="padding: 4px;">{escape_html(str(row.get(col, "")))}</td>'
            for col in columns
        )
        body += f"<tr>{cells}</tr>"

    return (
        '<table style="width: 100%; border-collapse: collapse;">'
        f"<tr>{header}</tr>{body}</table>"
    )


def render_result(container: ui.element, result: CommandResult) -> None:
    """Render a CommandResult into a NiceGUI container.

    Handles tabular data (result.rows) as HTML tables and
    plain messages as system message cards.
    """
    from theact.web.components.system_message import show_system_message

    content = ""
    if result.title:
        content += (
            f'<div style="font-weight: bold; margin-bottom: 8px;">'
            f"{escape_html(result.title)}</div>"
        )

    if result.rows:
        content += render_table_html(result.rows)
    elif result.message:
        content += text_to_html(result.message)

    if content:
        show_system_message(container, content)


def relative_time(timestamp: float) -> str:
    """Convert a Unix timestamp to a human-readable relative time string."""
    now = time.time()
    diff = now - timestamp

    if diff < 60:
        return "just now"
    elif diff < 3600:
        minutes = int(diff / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff < 86400:
        hours = int(diff / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff < 604800:
        days = int(diff / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        weeks = int(diff / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
