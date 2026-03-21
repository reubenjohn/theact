"""Playtest report generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from theact.playtest.config import PlaytestConfig
from theact.playtest.logger import PlaytestLogger


@dataclass
class PlaytestReport:
    """Summary of a playtest run."""

    game_id: str
    game_title: str
    timestamp: str
    model: str
    turns_played: int
    max_turns: int
    total_duration_seconds: float
    issue_count: int
    error_count: int
    issues: list[tuple[int, str]]  # (turn, issue description)
    errors: list[tuple[int, str]]  # (turn, error message)
    events: list[tuple[int, str, str]]  # (turn, event, detail)
    per_turn: list[dict]  # per-turn summary dicts
    memory_final: dict[str, str]  # character -> summary at end
    output_path: str = ""  # set after writing

    # Aggregate stats
    avg_turn_seconds: float = 0.0
    slowest_turn_seconds: float = 0.0
    fastest_turn_seconds: float = 0.0


def generate_report(
    logger: PlaytestLogger,
    config: PlaytestConfig,
    game_title: str,
    total_duration: float,
    memory_final: dict[str, str] | None = None,
) -> PlaytestReport:
    """Compile logger data into a PlaytestReport."""
    turns_played = len(logger.turns)
    issues = logger.all_issues()

    per_turn: list[dict] = []
    elapsed_values: list[float] = []

    for t in logger.turns:
        per_turn.append(
            {
                "turn": t.turn,
                "elapsed": round(t.elapsed_seconds, 2),
                "characters_responded": t.characters_responded,
                "beats_hit": t.beats_hit,
                "issues": t.issues,
                "is_edge_case": t.is_edge_case,
            }
        )
        if t.elapsed_seconds > 0:
            elapsed_values.append(t.elapsed_seconds)

    avg_turn = sum(elapsed_values) / len(elapsed_values) if elapsed_values else 0.0
    slowest = max(elapsed_values) if elapsed_values else 0.0
    fastest = min(elapsed_values) if elapsed_values else 0.0

    return PlaytestReport(
        game_id=config.game_id,
        game_title=game_title,
        timestamp=config.timestamp,
        model=config.llm_config.model,
        turns_played=turns_played,
        max_turns=config.max_turns,
        total_duration_seconds=total_duration,
        issue_count=len(issues),
        error_count=len(logger.errors),
        issues=issues,
        errors=logger.errors,
        events=logger.events,
        per_turn=per_turn,
        memory_final=memory_final or {},
        avg_turn_seconds=round(avg_turn, 2),
        slowest_turn_seconds=round(slowest, 2),
        fastest_turn_seconds=round(fastest, 2),
    )


def generate_report_markdown(report: PlaytestReport) -> str:
    """Generate a human-readable markdown report."""
    lines: list[str] = []

    # Header
    lines.append("# Playtest Report")
    lines.append("")
    lines.append(f"**Game:** {report.game_title}")
    lines.append(f"**Date:** {report.timestamp}")
    lines.append(f"**Turns:** {report.turns_played} / {report.max_turns}")

    minutes = int(report.total_duration_seconds // 60)
    seconds = int(report.total_duration_seconds % 60)
    lines.append(f"**Duration:** {minutes}m {seconds}s")
    lines.append(f"**Model:** {report.model}")
    lines.append("")

    # Issues
    lines.append("## Issues")
    lines.append("")
    if report.issues:
        lines.append("| Turn | Issue |")
        lines.append("|------|-------|")
        for turn, issue in report.issues:
            lines.append(f"| {turn} | {issue} |")
    else:
        lines.append("No issues detected.")
    lines.append("")

    # Errors
    if report.errors:
        lines.append("## Errors")
        lines.append("")
        lines.append("| Turn | Error |")
        lines.append("|------|-------|")
        for turn, error in report.errors:
            lines.append(f"| {turn} | {error} |")
        lines.append("")

    # Timing
    lines.append("## Timing")
    lines.append("")
    lines.append(f"- Average turn: {report.avg_turn_seconds}s")
    lines.append(f"- Slowest turn: {report.slowest_turn_seconds}s")
    lines.append(f"- Fastest turn: {report.fastest_turn_seconds}s")
    lines.append("")

    # Per-Turn Detail
    lines.append("## Per-Turn Detail")
    lines.append("")
    lines.append("| Turn | Elapsed | Characters Responded | Issues |")
    lines.append("|------|---------|----------------------|--------|")
    for pt in report.per_turn:
        chars = (
            ", ".join(pt["characters_responded"])
            if pt["characters_responded"]
            else "(none)"
        )
        issues_str = ", ".join(pt["issues"]) if pt["issues"] else ""
        lines.append(f"| {pt['turn']} | {pt['elapsed']}s | {chars} | {issues_str} |")
    lines.append("")

    # Events
    if report.events:
        lines.append("## Events")
        lines.append("")
        for turn, event, detail in report.events:
            lines.append(f"- Turn {turn}: {event} {detail}")
        lines.append("")

    # Memory State
    if report.memory_final:
        lines.append("## Memory State (Final)")
        lines.append("")
        for char_name, summary in report.memory_final.items():
            lines.append(f"### {char_name}")
            lines.append(f"Summary: {summary}")
            lines.append("")

    return "\n".join(lines)


def write_report(
    report: PlaytestReport,
    logger: PlaytestLogger,
    config: PlaytestConfig,
) -> str:
    """Write all report files to disk. Returns the output directory path."""
    out_path = Path(config.output_dir) / config.timestamp
    out_path.mkdir(parents=True, exist_ok=True)

    # Write report.md
    md = generate_report_markdown(report)
    with open(out_path / "report.md", "w") as f:
        f.write(md)

    # Write config.yaml
    config_data = {
        "game_id": config.game_id,
        "max_turns": config.max_turns,
        "player_name": config.player_name,
        "opening_action": config.opening_action,
        "stop_on_error": config.stop_on_error,
        "edge_case_frequency": config.edge_case_frequency,
        "timestamp": config.timestamp,
        "model": config.llm_config.model,
        "output_dir": config.output_dir,
    }
    with open(out_path / "config.yaml", "w") as f:
        yaml.dump(
            config_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    # Write memory_final.yaml
    if report.memory_final:
        with open(out_path / "memory_final.yaml", "w") as f:
            yaml.dump(
                report.memory_final,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    # Flush remaining logger data (conversation, errors, timing)
    logger.flush_to_disk(config.output_dir, config.timestamp)

    output_str = str(out_path)
    report.output_path = output_str
    return output_str
