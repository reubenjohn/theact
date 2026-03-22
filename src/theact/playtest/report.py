"""Playtest report generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from theact.playtest.config import PlaytestConfig
from theact.playtest.logger import PlaytestLogger

if TYPE_CHECKING:
    from theact.llm.call_log import LLMCallLog


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
    memory_final_facts: dict[str, list[str]] = field(
        default_factory=dict
    )  # character -> final facts
    output_path: str = ""  # set after writing

    # Aggregate stats
    avg_turn_seconds: float = 0.0
    slowest_turn_seconds: float = 0.0
    fastest_turn_seconds: float = 0.0

    # Quality scoring
    character_response_rate: float = 0.0  # % of turns with >= 1 character
    yaml_parse_success_rate: float = 0.0  # % of turns without parse failure
    quality_scores: list[dict] = field(default_factory=list)  # per-turn scores

    # Memory health stats
    memory_health: dict = field(default_factory=dict)

    # LLM call log stats (populated when call_log is provided)
    call_log_summary: dict = field(default_factory=dict)
    call_log_totals: dict = field(default_factory=dict)
    parse_failure_breakdown: dict = field(default_factory=dict)


def _compute_memory_health(logger: PlaytestLogger) -> dict:
    """Compute aggregate memory health statistics from turn logs."""
    from theact.agents.prompts import MAX_KEY_FACTS

    # Collect per-character, per-turn fact data
    char_fact_history: dict[str, list[list[str]]] = {}
    overlap_counts: dict[str, int] = 0  # type: ignore[assignment]
    overlap_counts = {}
    overflow_counts: dict[str, int] = {}
    stale_counts: dict[str, int] = {}
    turns_with_memory = 0

    for t in logger.turns:
        if not t.memory_facts:
            continue
        turns_with_memory += 1
        for char, facts in t.memory_facts.items():
            char_fact_history.setdefault(char, []).append(facts)

            # At cap?
            if len(facts) > MAX_KEY_FACTS:
                overflow_counts[char] = overflow_counts.get(char, 0) + 1

            # Overlap with summary?
            summary = t.memory_updates.get(char, "")
            if summary and facts:
                summary_words = {
                    w.strip(".,;:!?\"'()")
                    for w in summary.lower().split()
                    if len(w) > 3
                }
                for fact in facts:
                    fact_words = [
                        w.strip(".,;:!?\"'()")
                        for w in fact.lower().split()
                        if len(w) > 3
                    ]
                    if (
                        fact_words
                        and sum(1 for w in fact_words if w in summary_words)
                        / len(fact_words)
                        > 0.7
                    ):
                        overlap_counts[char] = overlap_counts.get(char, 0) + 1
                        break

    # Stale: facts identical to previous turn
    for char, history in char_fact_history.items():
        for i in range(1, len(history)):
            if history[i] == history[i - 1]:
                stale_counts[char] = stale_counts.get(char, 0) + 1

    # Per-character summary
    per_character: dict[str, dict] = {}
    for char, history in char_fact_history.items():
        fact_counts = [len(f) for f in history]
        per_character[char] = {
            "avg_fact_count": round(sum(fact_counts) / len(fact_counts), 1),
            "max_fact_count": max(fact_counts),
            "turns_overflow": overflow_counts.get(char, 0),
            "turns_with_overlap": overlap_counts.get(char, 0),
            "turns_stale": stale_counts.get(char, 0),
            "total_turns": len(history),
        }

    return {
        "per_character": per_character,
        "turns_with_memory": turns_with_memory,
    }


def generate_report(
    logger: PlaytestLogger,
    config: PlaytestConfig,
    game_title: str,
    total_duration: float,
    memory_final: dict[str, str] | None = None,
    memory_final_facts: dict[str, list[str]] | None = None,
    call_log: LLMCallLog | None = None,
    quality_scores: list[dict] | None = None,
) -> PlaytestReport:
    """Compile logger data into a PlaytestReport.

    Args:
        call_log: Optional LLMCallLog to include call statistics in the report.
        quality_scores: Optional per-turn quality score dicts from scoring module.
    """
    from theact.llm.call_log import LLMCallLog as _LLMCallLog  # runtime import

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

    # Character response rate: % of turns with >= 1 character responding
    turns_with_chars = sum(1 for t in logger.turns if t.characters_responded)
    character_response_rate = turns_with_chars / turns_played if turns_played else 0.0

    # YAML parse success rate: % of turns without parse-related issues
    turns_with_parse_issues = sum(
        1
        for t in logger.turns
        if any("yaml" in i.lower() or "parse" in i.lower() for i in t.issues)
    )
    yaml_parse_success_rate = (
        (turns_played - turns_with_parse_issues) / turns_played if turns_played else 0.0
    )

    # Compute call log stats if available
    call_log_summary: dict = {}
    call_log_totals: dict = {}
    parse_failure_breakdown: dict = {}

    if call_log and isinstance(call_log, _LLMCallLog) and call_log.records:
        call_log_summary = call_log.agent_summary()
        call_log_totals = call_log.summary()

        # Build parse failure breakdown
        failures: dict[str, int] = {}
        for r in call_log.records:
            if r.parse_result != "success":
                failures[r.parse_result] = failures.get(r.parse_result, 0) + 1
        parse_failure_breakdown = failures

    memory_health = _compute_memory_health(logger)

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
        memory_final_facts=memory_final_facts or {},
        avg_turn_seconds=round(avg_turn, 2),
        slowest_turn_seconds=round(slowest, 2),
        fastest_turn_seconds=round(fastest, 2),
        character_response_rate=round(character_response_rate, 3),
        yaml_parse_success_rate=round(yaml_parse_success_rate, 3),
        quality_scores=quality_scores or [],
        memory_health=memory_health,
        call_log_summary=call_log_summary,
        call_log_totals=call_log_totals,
        parse_failure_breakdown=parse_failure_breakdown,
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

    # Quality Scores
    if report.quality_scores:
        lines.append("## Quality Scores")
        lines.append("")
        lines.append(
            "| Turn | Narration Length | YAML First Try "
            "| Character Personality | Memory Relevance | Composite |"
        )
        lines.append(
            "|------|-----------------|----------------"
            "|----------------------|------------------|-----------|"
        )
        for qs in report.quality_scores:
            ok = "ok" if qs.get("narration_length_ok") else "bad"
            yaml_ok = "yes" if qs.get("yaml_first_attempt") else "no"
            personality = f"{qs.get('character_personality', 0.0):.2f}"
            mem = "yes" if qs.get("memory_relevance") else "no"
            comp = f"{qs.get('composite', 0.0):.2f}"
            lines.append(
                f"| {qs.get('turn', '?')} | {ok} | {yaml_ok} "
                f"| {personality} | {mem} | {comp} |"
            )
        lines.append("")

        # Average composite
        composites = [qs.get("composite", 0.0) for qs in report.quality_scores]
        if composites:
            avg_composite = sum(composites) / len(composites)
            lines.append(f"**Average composite score:** {avg_composite:.2f}")
            lines.append("")

        # Character response rate and YAML parse success rate
        lines.append(f"- Character response rate: {report.character_response_rate:.1%}")
        lines.append(f"- YAML parse success rate: {report.yaml_parse_success_rate:.1%}")
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

    # LLM Call Summary
    if report.call_log_totals:
        lines.append("## LLM Call Summary")
        lines.append("")
        totals = report.call_log_totals
        lines.append(f"- Total calls: {totals.get('total_calls', 0)}")
        lines.append(f"- Mean latency: {totals.get('mean_latency_ms', 0)}ms")
        lines.append(f"- Parse success rate: {totals.get('parse_success_rate', 0):.1%}")
        lines.append(f"- Total prompt tokens: {totals.get('total_prompt_tokens', 0)}")
        lines.append(
            f"- Total thinking tokens: {totals.get('total_thinking_tokens', 0)}"
        )
        lines.append(f"- Total content tokens: {totals.get('total_content_tokens', 0)}")
        lines.append(f"- Length finishes: {totals.get('length_finishes', 0)}")
        lines.append(f"- Total retries: {totals.get('total_retries', 0)}")
        lines.append("")

        # Per-agent breakdown table
        if report.call_log_summary:
            lines.append("| Agent | Calls | Mean Latency | Parse Rate | Retries |")
            lines.append("|-------|-------|-------------|------------|---------|")
            for agent, stats in report.call_log_summary.items():
                lines.append(
                    f"| {agent} | {stats['total_calls']} | "
                    f"{stats['mean_latency_ms']}ms | "
                    f"{stats['parse_success_rate']:.1%} | "
                    f"{stats['total_retries']} |"
                )
            lines.append("")

        # Parse failure breakdown
        if report.parse_failure_breakdown:
            lines.append("### Parse Failures")
            lines.append("")
            for failure_type, count in report.parse_failure_breakdown.items():
                lines.append(f"- {failure_type}: {count}")
            lines.append("")

    # Memory Health
    if report.memory_health and report.memory_health.get("per_character"):
        lines.append("## Memory Health")
        lines.append("")
        lines.append(
            "| Character | Avg Facts | Max Facts | Overflow | Overlap | Stale | Turns |"
        )
        lines.append(
            "|-----------|-----------|----------|----------|---------|-------|-------|"
        )
        for char, stats in report.memory_health["per_character"].items():
            lines.append(
                f"| {char} | {stats['avg_fact_count']} | {stats['max_fact_count']} "
                f"| {stats['turns_overflow']} | {stats['turns_with_overlap']} "
                f"| {stats['turns_stale']} | {stats['total_turns']} |"
            )
        lines.append("")
        lines.append(
            "- **Overflow**: turns where model output exceeded MAX_KEY_FACTS "
            "(facts were truncated)"
        )
        lines.append(
            "- **Overlap**: turns where a fact repeated content already in the summary"
        )
        lines.append("- **Stale**: turns where facts were identical to previous turn")
        lines.append("")

    # Memory State (Final)
    if report.memory_final:
        lines.append("## Memory State (Final)")
        lines.append("")
        for char_name, summary in report.memory_final.items():
            lines.append(f"### {char_name}")
            lines.append(f"**Summary:** {summary}")
            facts = report.memory_final_facts.get(char_name, [])
            if facts:
                lines.append("**Facts:**")
                for f in facts:
                    lines.append(f"- {f}")
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

    # Write memory_final.yaml (summary + facts per character)
    if report.memory_final:
        memory_data = {}
        for char, summary in report.memory_final.items():
            memory_data[char] = {
                "summary": summary,
                "facts": report.memory_final_facts.get(char, []),
            }
        with open(out_path / "memory_final.yaml", "w") as f:
            yaml.dump(
                memory_data,
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
