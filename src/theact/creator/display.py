"""Rich-formatted display helpers for proposals, game files, errors, and warnings."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from theact.creator.validator import ValidationError, ValidationResult

console = Console()


def display_proposal(proposal: dict) -> None:
    """Display a game proposal in a readable format."""
    lines: list[str] = []
    lines.append(f"Title: {proposal.get('title', '?')}")
    lines.append(f"ID: {proposal.get('id', '?')}")
    lines.append("")

    if "setting" in proposal:
        lines.append(f"Setting: {proposal['setting'].strip()}")
        lines.append("")

    if "tone" in proposal:
        lines.append(f"Tone: {proposal['tone'].strip()}")
        lines.append("")

    if "rules" in proposal:
        lines.append(f"Rules: {proposal['rules'].strip()}")
        lines.append("")

    chars = proposal.get("characters", [])
    if chars:
        lines.append("Characters:")
        for i, c in enumerate(chars, 1):
            if isinstance(c, dict):
                name = c.get("name", "?")
                role = c.get("role", "?")
                lines.append(f"  {i}. {name} -- {role}")
            else:
                lines.append(f"  {i}. {c}")
        lines.append("")

    chapters = proposal.get("chapters", [])
    if chapters:
        lines.append("Chapters:")
        for i, ch in enumerate(chapters, 1):
            if isinstance(ch, dict):
                title = ch.get("title", "?")
                cid = ch.get("id", "?")
                summary = ch.get("summary", "")
                lines.append(f"  {i}. {title} ({cid}) -- {summary}")
            else:
                lines.append(f"  {i}. {ch}")

    panel = Panel(
        "\n".join(lines),
        title="GAME PROPOSAL",
        border_style="cyan",
    )
    console.print(panel)


def display_game_files(result: ValidationResult) -> None:
    """Display all generated game files in a readable format."""
    if result.game:
        console.print(
            Panel(
                f"ID: {result.game.id}\n"
                f"Title: {result.game.title}\n"
                f"Description: {result.game.description}\n"
                f"Characters: {', '.join(result.game.characters)}\n"
                f"Chapters: {', '.join(result.game.chapters)}",
                title="game.yaml",
                border_style="green",
            )
        )

    if result.world:
        console.print(
            Panel(
                f"Setting: {result.world.setting.strip()}\n\n"
                f"Tone: {result.world.tone.strip()}\n\n"
                f"Rules: {result.world.rules.strip()}",
                title="world.yaml",
                border_style="green",
            )
        )

    for stem, char in result.characters.items():
        rels = "\n".join(f"    {k}: {v}" for k, v in char.relationships.items())
        console.print(
            Panel(
                f"Name: {char.name}\n"
                f"Role: {char.role}\n"
                f"Personality: {char.personality.strip()}\n"
                f"Secret: {char.secret}\n"
                f"Relationships:\n{rels}",
                title=f"characters/{stem}.yaml",
                border_style="green",
            )
        )

    for cid, chap in result.chapters.items():
        beats = "\n".join(f"  - {b}" for b in chap.beats)
        chars = ", ".join(chap.characters)
        next_ch = chap.next or "(final chapter)"
        console.print(
            Panel(
                f"Title: {chap.title}\n"
                f"Summary: {chap.summary.strip()}\n"
                f"Beats:\n{beats}\n"
                f"Completion: {chap.completion}\n"
                f"Characters: {chars}\n"
                f"Next: {next_ch}",
                title=f"chapters/{cid}.yaml",
                border_style="green",
            )
        )


def display_validation_errors(errors: list[ValidationError]) -> None:
    """Display validation errors."""
    lines: list[str] = []
    for err in errors:
        field_info = f" [{err.field}]" if err.field else ""
        lines.append(f"  {err.file}{field_info}: {err.message}")

    text = Text("\n".join(lines))
    panel = Panel(text, title="Validation Errors", border_style="red")
    console.print(panel)


def display_size_warnings(warnings: list[str]) -> None:
    """Display size warnings."""
    lines = [f"  - {w}" for w in warnings]
    text = Text("\n".join(lines))
    panel = Panel(text, title="Size Warnings", border_style="yellow")
    console.print(panel)
