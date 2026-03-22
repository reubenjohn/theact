#!/usr/bin/env python
"""Run an automated playtest session.

Usage:
    uv run python scripts/playtest.py --game lost-island --turns 20
    uv run python scripts/playtest.py --game lost-island --turns 10 --stop-on-error
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime

from dotenv import load_dotenv

from theact.llm.config import load_llm_config
from theact.playtest.config import PlaytestConfig
from theact.playtest.runner import PlaytestRunner


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run an automated playtest")
    parser.add_argument("--game", required=True, help="Game ID (e.g. lost-island)")
    parser.add_argument("--turns", type=int, default=20, help="Max turns to play")
    parser.add_argument("--player-name", default="Alex", help="Player character name")
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop on first error",
    )
    parser.add_argument(
        "--edge-case-freq",
        type=float,
        default=0.15,
        help="Frequency of edge case actions (0.0 to 1.0)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Write per-turn diagnostics artifacts",
    )
    parser.add_argument(
        "--report-dir",
        default="playtests",
        help="Base directory for playtest reports",
    )
    parser.add_argument(
        "--save-id",
        default=None,
        help="Custom save ID (default: auto-generated from timestamp)",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Load LLM config from environment
    try:
        llm_config = load_llm_config()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    config = PlaytestConfig(
        game_id=args.game,
        max_turns=args.turns,
        player_name=args.player_name,
        stop_on_error=args.stop_on_error,
        edge_case_frequency=args.edge_case_freq,
        timestamp=timestamp,
        llm_config=llm_config,
        output_dir=args.report_dir,
        debug=args.debug,
    )

    print(f"Starting playtest: game={config.game_id}, turns={config.max_turns}")
    print(f"Model: {llm_config.model}")
    print(f"Output: {config.output_dir}/{config.timestamp}/")
    print()

    runner = PlaytestRunner(config)
    report = asyncio.run(runner.run())

    print()
    print(f"Playtest complete. Report saved to: {report.output_path}")
    print(f"Turns played: {report.turns_played}/{config.max_turns}")
    print(f"Issues found: {report.issue_count}")
    print(f"Errors: {report.error_count}")


if __name__ == "__main__":
    main()
