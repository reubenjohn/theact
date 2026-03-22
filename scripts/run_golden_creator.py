#!/usr/bin/env python3
"""Run golden creator scenarios against the live model.

Golden creator scenarios test the game creation pipeline: concept hint
extraction, setting generation, character proposal, and chapter proposal.
Each scenario provides a concept and structural assertions on the outputs.

Usage:
    uv run python scripts/run_golden_creator.py                           # all scenarios
    uv run python scripts/run_golden_creator.py --scenario two_chars_noir  # one scenario
    uv run python scripts/run_golden_creator.py --hints-only               # only test hints (no LLM)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI

from theact.creator.concept_hints import ConceptHints, extract_concept_hints
from theact.creator.config import CreatorLLMConfig, load_creator_config
from theact.creator.proposer import (
    generate_chapters_proposal,
    generate_characters_proposal,
    generate_setting,
)

SCENARIOS_DIR = Path(__file__).parent.parent / "tests" / "golden_creator_scenarios"


def load_scenario(path: Path) -> dict:
    """Load a golden creator scenario YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Assertion evaluators
# ---------------------------------------------------------------------------


def evaluate_hints_assertions(
    hints: ConceptHints,
    expect: dict,
) -> list[str]:
    """Check assertions on ConceptHints. Returns list of failure messages."""
    failures: list[str] = []

    if "character_count" in expect:
        expected = expect["character_count"]
        if hints.character_count != expected:
            failures.append(
                f"hints.character_count: expected {expected!r}, got {hints.character_count!r}"
            )

    if "chapter_count" in expect:
        expected = expect["chapter_count"]
        if hints.chapter_count != expected:
            failures.append(
                f"hints.chapter_count: expected {expected!r}, got {hints.chapter_count!r}"
            )

    if "character_names_include" in expect:
        for name in expect["character_names_include"]:
            if name not in hints.character_names:
                failures.append(
                    f"hints.character_names_include: '{name}' not in {hints.character_names}"
                )

    return failures


def evaluate_setting_assertions(
    setting_data: dict,
    expect: dict,
) -> list[str]:
    """Check assertions on setting output. Returns list of failure messages."""
    failures: list[str] = []

    if expect.get("has_title"):
        title = setting_data.get("title")
        if not title or not str(title).strip():
            failures.append("setting.has_title: title is missing or empty")

    if expect.get("has_id"):
        id_val = setting_data.get("id")
        if not id_val or not str(id_val).strip():
            failures.append("setting.has_id: id is missing or empty")

    return failures


def evaluate_count_assertions(
    items: list,
    label: str,
    expect: dict,
) -> list[str]:
    """Check count / count_min / count_max assertions on a list."""
    failures: list[str] = []
    actual = len(items)

    if "count" in expect:
        expected = expect["count"]
        if actual != expected:
            failures.append(f"{label}.count: expected {expected}, got {actual}")

    if "count_min" in expect:
        expected_min = expect["count_min"]
        if actual < expected_min:
            failures.append(
                f"{label}.count_min: expected >= {expected_min}, got {actual}"
            )

    if "count_max" in expect:
        expected_max = expect["count_max"]
        if actual > expected_max:
            failures.append(
                f"{label}.count_max: expected <= {expected_max}, got {actual}"
            )

    return failures


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------


async def run_scenario(
    scenario: dict,
    client: AsyncOpenAI | None,
    config: CreatorLLMConfig | None,
    hints_only: bool = False,
) -> dict:
    """Run a single golden creator scenario and return results."""
    scenario_name = scenario["name"]
    concept = scenario["concept"]
    assertions = scenario.get("assertions", {})

    all_failures: list[tuple[str, list[str]]] = []

    # --- Hints (always runs, no LLM) ---
    hints = extract_concept_hints(concept)

    if "hints" in assertions:
        failures = evaluate_hints_assertions(hints, assertions["hints"])
        all_failures.append(("hints", failures))

    if hints_only:
        passed = all(len(f) == 0 for _, f in all_failures)
        return _build_result(scenario_name, all_failures, passed)

    # LLM steps require client and config
    assert client is not None and config is not None

    # --- Setting (LLM) ---
    setting_data: dict = {}
    if "setting" in assertions:
        try:
            setting_data = await generate_setting(concept, client, config)
            failures = evaluate_setting_assertions(setting_data, assertions["setting"])
            all_failures.append(("setting", failures))
        except Exception as e:
            all_failures.append(("setting", [f"EXCEPTION: {type(e).__name__}: {e}"]))
    else:
        # Even without assertions we need setting_data for downstream steps
        try:
            setting_data = await generate_setting(concept, client, config)
        except Exception as e:
            all_failures.append(
                ("setting (implicit)", [f"EXCEPTION: {type(e).__name__}: {e}"])
            )
            passed = False
            return _build_result(scenario_name, all_failures, passed)

    # --- Characters (LLM) ---
    characters_data: dict = {}
    if "characters" in assertions or "chapters" in assertions:
        try:
            characters_data = await generate_characters_proposal(
                setting_data, client, config, concept=concept, hints=hints
            )
        except Exception as e:
            all_failures.append(("characters", [f"EXCEPTION: {type(e).__name__}: {e}"]))

    if "characters" in assertions and not any(
        label == "characters" and failures
        for label, failures in all_failures
        if isinstance(failures, list) and any("EXCEPTION" in f for f in failures)
    ):
        chars_list = characters_data.get("characters", [])
        failures = evaluate_count_assertions(
            chars_list, "characters", assertions["characters"]
        )
        all_failures.append(("characters", failures))

    # --- Chapters (LLM) ---
    if "chapters" in assertions:
        try:
            chapters_data = await generate_chapters_proposal(
                setting_data,
                characters_data,
                client,
                config,
                concept=concept,
                hints=hints,
            )
            chaps_list = chapters_data.get("chapters", [])
            failures = evaluate_count_assertions(
                chaps_list, "chapters", assertions["chapters"]
            )
            all_failures.append(("chapters", failures))
        except Exception as e:
            all_failures.append(("chapters", [f"EXCEPTION: {type(e).__name__}: {e}"]))

    passed = all(len(f) == 0 for _, f in all_failures)
    return _build_result(scenario_name, all_failures, passed)


def _build_result(
    scenario_name: str,
    all_failures: list[tuple[str, list[str]]],
    passed: bool,
) -> dict:
    """Build a structured result dict for reporting."""
    return {
        "scenario": scenario_name,
        "passed": passed,
        "steps": [
            {"step": label, "passed": len(failures) == 0, "failures": failures}
            for label, failures in all_failures
        ],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_results(results: list[dict]) -> None:
    """Print scenario results to stdout."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    print()
    print("=" * 60)
    print("GOLDEN CREATOR SCENARIO RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"\n  [{status}] {result['scenario']}")

        for step in result["steps"]:
            s_status = "ok" if step["passed"] else "FAIL"
            print(f"    {step['step']}: [{s_status}]")

            if not step["passed"]:
                for failure in step["failures"]:
                    print(f"      - {failure}")

    print()
    print("-" * 60)
    print(f"Total: {total} scenarios, {passed} passed, {failed} failed")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """Parse args, load scenarios, run, report."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Run golden creator scenarios against the live model"
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Run a single scenario by filename stem (e.g. two_chars_noir)",
    )
    parser.add_argument(
        "--hints-only",
        action="store_true",
        help="Only test hint extraction (no LLM calls)",
    )
    parser.add_argument(
        "--scenarios-dir",
        default=str(SCENARIOS_DIR),
        help="Path to golden creator scenarios directory",
    )
    args = parser.parse_args()

    scenarios_dir = Path(args.scenarios_dir)

    if not scenarios_dir.exists():
        print(
            f"Error: scenarios directory not found: {scenarios_dir}",
            file=sys.stderr,
        )
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
            print(
                f"Error: no scenarios found in {scenarios_dir}",
                file=sys.stderr,
            )
            sys.exit(1)

    # Set up LLM client (skip if hints-only)
    client: AsyncOpenAI | None = None
    config: CreatorLLMConfig | None = None

    if not args.hints_only:
        config = load_creator_config()
        client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)

    mode = "hints-only" if args.hints_only else "full (with LLM)"
    print(f"Running {len(scenario_files)} golden creator scenario(s) [{mode}]...")

    results: list[dict] = []
    for sf in scenario_files:
        scenario = load_scenario(sf)
        print(f"  Running: {scenario['name']}...")
        result = await run_scenario(
            scenario,
            client=client,
            config=config,
            hints_only=args.hints_only,
        )
        results.append(result)

    print_results(results)

    # Exit with non-zero if any failed
    if any(not r["passed"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
