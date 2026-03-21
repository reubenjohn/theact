#!/usr/bin/env python3
"""Run golden scenarios against the live model.

Golden scenarios are pre-defined turn sequences with expected outcomes.
Each scenario creates a fresh save, runs scripted turns, and evaluates
assertions on the results.

Usage:
    uv run python scripts/run_golden.py                           # all scenarios
    uv run python scripts/run_golden.py --scenario crash_opening  # single
    uv run python scripts/run_golden.py --games-dir games/        # custom games dir
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import yaml
from dotenv import load_dotenv

from theact.engine.turn import run_turn
from theact.engine.types import TurnResult
from theact.io.save_manager import create_save, load_save
from theact.llm.config import load_llm_config

SCENARIOS_DIR = Path(__file__).parent.parent / "tests" / "golden_scenarios"
GAMES_DIR = Path(__file__).parent.parent / "games"
SAVES_DIR = Path(__file__).parent.parent / "saves"


def load_scenario(path: Path) -> dict:
    """Load a golden scenario YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def evaluate_assertions(turn_result: TurnResult, expect: dict) -> list[str]:
    """Check each assertion type and return list of failure messages."""
    failures: list[str] = []

    # narrator_not_empty
    if expect.get("narrator_not_empty"):
        if not turn_result.narrator.narration.strip():
            failures.append("narrator_not_empty: narration was empty")

    # narrator_word_count_min
    min_words = expect.get("narrator_word_count_min")
    if min_words is not None:
        actual = len(turn_result.narrator.narration.split())
        if actual < min_words:
            failures.append(
                f"narrator_word_count_min: expected >= {min_words}, got {actual}"
            )

    # narrator_word_count_max
    max_words = expect.get("narrator_word_count_max")
    if max_words is not None:
        actual = len(turn_result.narrator.narration.split())
        if actual > max_words:
            failures.append(
                f"narrator_word_count_max: expected <= {max_words}, got {actual}"
            )

    # characters_responded_min
    min_chars = expect.get("characters_responded_min")
    if min_chars is not None:
        actual = len(turn_result.characters)
        if actual < min_chars:
            failures.append(
                f"characters_responded_min: expected >= {min_chars}, got {actual}"
            )

    # characters_responded_max
    max_chars = expect.get("characters_responded_max")
    if max_chars is not None:
        actual = len(turn_result.characters)
        if actual > max_chars:
            failures.append(
                f"characters_responded_max: expected <= {max_chars}, got {actual}"
            )

    # characters_responded_includes
    includes = expect.get("characters_responded_includes")
    if includes is not None:
        responded_ids = set(turn_result.narrator.responding_characters)
        for char_id in includes:
            if char_id not in responded_ids:
                failures.append(
                    f"characters_responded_includes: '{char_id}' not in responding "
                    f"characters {sorted(responded_ids)}"
                )

    # beats_hit_any
    if expect.get("beats_hit_any"):
        gs = turn_result.game_state
        if gs is None or not gs.beats_hit:
            failures.append("beats_hit_any: no beats were hit")

    # beats_hit_count_min
    min_beats = expect.get("beats_hit_count_min")
    if min_beats is not None:
        gs = turn_result.game_state
        actual = len(gs.beats_hit) if gs else 0
        if actual < min_beats:
            failures.append(
                f"beats_hit_count_min: expected >= {min_beats}, got {actual}"
            )

    return failures


async def run_scenario(
    scenario: dict,
    games_dir: Path,
    saves_dir: Path,
) -> dict:
    """Create save, run turns, evaluate, return results."""
    llm_config = load_llm_config()
    game_id = scenario["game"]
    scenario_name = scenario["name"]
    turns_spec = scenario["turns"]

    # Create a unique save for this scenario run
    save_id = f"golden-{uuid.uuid4().hex[:8]}"
    create_save(
        game_id=game_id,
        save_id=save_id,
        player_name="Alex",
        games_dir=games_dir,
        saves_dir=saves_dir,
    )
    game = load_save(save_id, saves_dir=saves_dir)

    turn_results: list[dict] = []
    all_passed = True

    for i, turn_spec in enumerate(turns_spec):
        player_input = turn_spec.get("input") or ""
        expect = turn_spec.get("expect", {})

        try:
            result = await run_turn(
                game,
                player_input=player_input,
                llm_config=llm_config,
            )
            failures = evaluate_assertions(result, expect)
            passed = len(failures) == 0

            turn_results.append(
                {
                    "turn_index": i,
                    "input": player_input or "(opening)",
                    "passed": passed,
                    "failures": failures,
                    "narrator_preview": result.narrator.narration[:100],
                    "characters_responded": [cr.character for cr in result.characters],
                }
            )

            if not passed:
                all_passed = False

        except Exception as e:
            turn_results.append(
                {
                    "turn_index": i,
                    "input": player_input or "(opening)",
                    "passed": False,
                    "failures": [f"EXCEPTION: {type(e).__name__}: {e}"],
                    "narrator_preview": "",
                    "characters_responded": [],
                }
            )
            all_passed = False

    return {
        "scenario": scenario_name,
        "passed": all_passed,
        "turns": turn_results,
    }


def print_results(results: list[dict]) -> None:
    """Print scenario results to stdout."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    print()
    print("=" * 60)
    print("GOLDEN SCENARIO RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"\n  [{status}] {result['scenario']}")

        for turn in result["turns"]:
            t_status = "ok" if turn["passed"] else "FAIL"
            input_label = turn["input"]
            if len(input_label) > 50:
                input_label = input_label[:47] + "..."
            print(f"    Turn {turn['turn_index']}: [{t_status}] input={input_label!r}")

            if not turn["passed"]:
                for failure in turn["failures"]:
                    print(f"      - {failure}")

    print()
    print("-" * 60)
    print(f"Total: {total} scenarios, {passed} passed, {failed} failed")
    print("=" * 60)


async def main() -> None:
    """Parse args, load scenarios, run, report."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Run golden scenarios against the live model"
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Run a single scenario by filename stem (e.g. crash_opening)",
    )
    parser.add_argument(
        "--games-dir",
        default=str(GAMES_DIR),
        help="Path to games directory",
    )
    parser.add_argument(
        "--saves-dir",
        default=str(SAVES_DIR),
        help="Path to saves directory",
    )
    parser.add_argument(
        "--scenarios-dir",
        default=str(SCENARIOS_DIR),
        help="Path to golden scenarios directory",
    )
    args = parser.parse_args()

    scenarios_dir = Path(args.scenarios_dir)
    games_dir = Path(args.games_dir)
    saves_dir = Path(args.saves_dir)

    if not scenarios_dir.exists():
        print(f"Error: scenarios directory not found: {scenarios_dir}", file=sys.stderr)
        sys.exit(1)

    # Collect scenario files
    if args.scenario:
        scenario_path = scenarios_dir / f"{args.scenario}.yaml"
        if not scenario_path.exists():
            print(f"Error: scenario not found: {scenario_path}", file=sys.stderr)
            sys.exit(1)
        scenario_files = [scenario_path]
    else:
        scenario_files = sorted(scenarios_dir.glob("*.yaml"))
        if not scenario_files:
            print(f"Error: no scenarios found in {scenarios_dir}", file=sys.stderr)
            sys.exit(1)

    print(f"Running {len(scenario_files)} golden scenario(s)...")

    results: list[dict] = []
    for sf in scenario_files:
        scenario = load_scenario(sf)
        print(f"  Running: {scenario['name']}...")
        result = await run_scenario(scenario, games_dir, saves_dir)
        results.append(result)

    print_results(results)

    # Exit with non-zero if any failed
    if any(not r["passed"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
