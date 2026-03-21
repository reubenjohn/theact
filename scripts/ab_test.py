#!/usr/bin/env python3
"""A/B test two prompt variants against each other.

Runs multiple playtests with each prompt variant and compares
aggregate metrics. Use this to evaluate whether a prompt change
improves or degrades model output quality.

Usage:
    uv run python scripts/ab_test.py \\
        --game lost-island \\
        --turns 10 \\
        --variant-a current \\
        --variant-b src/theact/agents/prompts_v2.py \\
        --runs 3

Variant A defaults to "current" (the prompts already in theact.agents.prompts).
Variant B must be a path to a Python module with the same prompt constants.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from theact.llm.config import load_llm_config
from theact.playtest.config import PlaytestConfig
from theact.playtest.report import PlaytestReport
from theact.playtest.runner import PlaytestRunner

logger = logging.getLogger(__name__)

# Prompt attributes that can be overridden in variant modules
PROMPT_ATTRS = [
    "NARRATOR_SYSTEM",
    "CHARACTER_SYSTEM",
    "MEMORY_UPDATE_SYSTEM",
    "GAME_STATE_SYSTEM",
    "CHAPTER_SUMMARY_SYSTEM",
    "ROLLING_SUMMARY_SYSTEM",
    "YAML_HINT_NARRATOR",
    "YAML_HINT_MEMORY",
    "YAML_HINT_GAME_STATE",
]


@dataclass
class RunResult:
    """Metrics from a single playtest run."""

    variant: str
    run_number: int
    turns_played: int
    yaml_parse_success_rate: float
    character_response_rate: float
    avg_turn_seconds: float
    issue_count: int
    error_count: int
    total_prompt_tokens: int
    total_thinking_tokens: int
    total_content_tokens: int
    beats_hit: int
    quality_composite: float


@dataclass
class VariantSummary:
    """Aggregate metrics for a variant across all runs."""

    name: str
    runs: list[RunResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.runs)

    def mean(self, attr: str) -> float:
        values = [getattr(r, attr) for r in self.runs]
        return sum(values) / len(values) if values else 0.0


def load_variant_module(path: str) -> object:
    """Load a Python module from a file path using importlib."""
    file_path = Path(path).resolve()
    if not file_path.exists():
        print(f"Error: variant file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("prompt_variant", str(file_path))
    if spec is None or spec.loader is None:
        print(f"Error: cannot load module from: {file_path}", file=sys.stderr)
        sys.exit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_prompts(variant_module: object) -> dict[str, str]:
    """Monkey-patch theact.agents.prompts with variant module attributes.

    Returns a dict of the original values so they can be restored.
    """
    import theact.agents.prompts as prompts_mod

    originals: dict[str, str] = {}
    for attr in PROMPT_ATTRS:
        if hasattr(variant_module, attr):
            originals[attr] = getattr(prompts_mod, attr)
            setattr(prompts_mod, attr, getattr(variant_module, attr))
    return originals


def restore_prompts(originals: dict[str, str]) -> None:
    """Restore original prompt values."""
    import theact.agents.prompts as prompts_mod

    for attr, value in originals.items():
        setattr(prompts_mod, attr, value)


def extract_run_result(
    variant_name: str,
    run_number: int,
    report: PlaytestReport,
) -> RunResult:
    """Extract metrics from a PlaytestReport into a RunResult."""
    # Count total beats hit across turns
    total_beats = sum(len(pt.get("beats_hit", [])) for pt in report.per_turn)

    # Compute average quality composite
    composites = [qs.get("composite", 0.0) for qs in report.quality_scores]
    avg_composite = sum(composites) / len(composites) if composites else 0.0

    return RunResult(
        variant=variant_name,
        run_number=run_number,
        turns_played=report.turns_played,
        yaml_parse_success_rate=report.yaml_parse_success_rate,
        character_response_rate=report.character_response_rate,
        avg_turn_seconds=report.avg_turn_seconds,
        issue_count=report.issue_count,
        error_count=report.error_count,
        total_prompt_tokens=report.call_log_totals.get("total_prompt_tokens", 0),
        total_thinking_tokens=report.call_log_totals.get("total_thinking_tokens", 0),
        total_content_tokens=report.call_log_totals.get("total_content_tokens", 0),
        beats_hit=total_beats,
        quality_composite=avg_composite,
    )


async def run_variant(
    variant_name: str,
    variant_path: str,
    game_id: str,
    turns: int,
    run_number: int,
    saves_dir: str,
    llm_config: object,
) -> RunResult:
    """Run a single playtest with a specific prompt variant."""
    # Set seed for reproducibility
    random.seed(run_number)

    # Apply prompt variant if not "current"
    originals: dict[str, str] = {}
    if variant_path != "current":
        variant_module = load_variant_module(variant_path)
        originals = patch_prompts(variant_module)

    try:
        timestamp = (
            datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            + f"-{variant_name}-run{run_number}"
        )

        config = PlaytestConfig(
            game_id=game_id,
            max_turns=turns,
            timestamp=timestamp,
            llm_config=llm_config,  # type: ignore[arg-type]
            output_dir=saves_dir,
        )

        runner = PlaytestRunner(config)
        report = await runner.run()

        return extract_run_result(variant_name, run_number, report)
    finally:
        # Always restore original prompts
        if originals:
            restore_prompts(originals)


def print_comparison(
    a_summary: VariantSummary,
    b_summary: VariantSummary,
) -> None:
    """Print a comparison table of the two variants."""
    metrics = [
        ("Turns Played", "turns_played", ".1f"),
        ("YAML Parse Success", "yaml_parse_success_rate", ".1%"),
        ("Character Response Rate", "character_response_rate", ".1%"),
        ("Avg Turn Seconds", "avg_turn_seconds", ".2f"),
        ("Issues", "issue_count", ".1f"),
        ("Errors", "error_count", ".1f"),
        ("Prompt Tokens", "total_prompt_tokens", ".0f"),
        ("Thinking Tokens", "total_thinking_tokens", ".0f"),
        ("Content Tokens", "total_content_tokens", ".0f"),
        ("Beats Hit", "beats_hit", ".1f"),
        ("Quality Composite", "quality_composite", ".3f"),
    ]

    a_name = a_summary.name
    b_name = b_summary.name

    # Header
    print()
    print("=" * 72)
    print("A/B Test Results")
    print("=" * 72)
    print(f"  Variant A: {a_name} ({a_summary.n} runs)")
    print(f"  Variant B: {b_name} ({b_summary.n} runs)")
    print()

    # Table header
    header = f"{'Metric':<25} {'A (mean)':>12} {'B (mean)':>12} {'Delta':>10}"
    print(header)
    print("-" * len(header))

    for label, attr, fmt in metrics:
        a_val = a_summary.mean(attr)
        b_val = b_summary.mean(attr)
        delta = b_val - a_val

        # Format values
        a_str = f"{a_val:{fmt}}"
        b_str = f"{b_val:{fmt}}"

        # Delta with direction indicator
        if abs(delta) < 1e-9:
            delta_str = "="
        else:
            sign = "+" if delta > 0 else ""
            if "%" in fmt:
                delta_str = f"{sign}{delta:{fmt}}"
            else:
                delta_str = f"{sign}{delta:{fmt}}"

        print(f"{label:<25} {a_str:>12} {b_str:>12} {delta_str:>10}")

    print()

    # Verdict heuristic: compare quality composite
    a_comp = a_summary.mean("quality_composite")
    b_comp = b_summary.mean("quality_composite")
    a_parse = a_summary.mean("yaml_parse_success_rate")
    b_parse = b_summary.mean("yaml_parse_success_rate")

    if b_comp > a_comp and b_parse >= a_parse:
        print(f">> Variant B ({b_name}) appears BETTER on composite + parse rate.")
    elif a_comp > b_comp and a_parse >= b_parse:
        print(f">> Variant A ({a_name}) appears BETTER on composite + parse rate.")
    else:
        print(">> Results are MIXED. Review individual metrics above.")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="A/B test prompt variants")
    parser.add_argument("--game", default="lost-island", help="Game ID to playtest")
    parser.add_argument("--turns", type=int, default=10, help="Turns per run")
    parser.add_argument(
        "--variant-a",
        default="current",
        help="Path to variant A prompts module, or 'current' (default: current)",
    )
    parser.add_argument(
        "--variant-b",
        required=True,
        help="Path to variant B prompts module",
    )
    parser.add_argument(
        "--runs", type=int, default=3, help="Number of runs per variant"
    )
    parser.add_argument(
        "--saves-dir",
        type=str,
        default=None,
        help="Base directory for playtest saves (default: playtests/ab-<timestamp>)",
    )
    args = parser.parse_args()

    # Load LLM config
    try:
        llm_config = load_llm_config()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Set up output directory
    ab_timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    saves_dir = args.saves_dir or f"playtests/ab-{ab_timestamp}"

    # Derive variant names for display
    a_name = "current" if args.variant_a == "current" else Path(args.variant_a).stem
    b_name = Path(args.variant_b).stem

    print(f"A/B Test: {a_name} vs {b_name}")
    print(f"Game: {args.game}, Turns: {args.turns}, Runs: {args.runs}")
    print(f"Model: {llm_config.model}")
    print(f"Output: {saves_dir}/")
    print()

    a_summary = VariantSummary(name=a_name)
    b_summary = VariantSummary(name=b_name)

    for run_num in range(1, args.runs + 1):
        # Alternate between variants for fairness (time-of-day effects, etc.)
        print(f"--- Run {run_num}/{args.runs}: Variant A ({a_name}) ---")
        start = time.monotonic()
        a_result = await run_variant(
            a_name,
            args.variant_a,
            args.game,
            args.turns,
            run_num,
            saves_dir,
            llm_config,
        )
        elapsed_a = time.monotonic() - start
        a_summary.runs.append(a_result)
        print(
            f"    Done in {elapsed_a:.1f}s | "
            f"YAML parse: {a_result.yaml_parse_success_rate:.0%} | "
            f"Composite: {a_result.quality_composite:.3f}"
        )

        print(f"--- Run {run_num}/{args.runs}: Variant B ({b_name}) ---")
        start = time.monotonic()
        b_result = await run_variant(
            b_name,
            args.variant_b,
            args.game,
            args.turns,
            run_num,
            saves_dir,
            llm_config,
        )
        elapsed_b = time.monotonic() - start
        b_summary.runs.append(b_result)
        print(
            f"    Done in {elapsed_b:.1f}s | "
            f"YAML parse: {b_result.yaml_parse_success_rate:.0%} | "
            f"Composite: {b_result.quality_composite:.3f}"
        )

    print_comparison(a_summary, b_summary)


if __name__ == "__main__":
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(main())
