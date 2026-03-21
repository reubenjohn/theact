#!/usr/bin/env python3
"""Interactive turn debugger for prompt engineering.

Two modes:
  Interactive (default): step through agents, replay, edit prompts, capture fixtures.
  Replay (--replay):     walk through historical turns of an existing save.

Usage:
  uv run python scripts/debug_turn.py --game lost-island --save my-debug --input "I look around."
  uv run python scripts/debug_turn.py --save my-debug --replay
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path so imports work when run as script
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TheAct Turn Debugger")
    parser.add_argument("--game", type=str, help="Game ID (e.g. lost-island)")
    parser.add_argument("--save", type=str, required=True, help="Save ID")
    parser.add_argument("--input", type=str, help="Player input text")
    parser.add_argument("--saves-dir", type=str, help="Saves directory path")
    parser.add_argument("--games-dir", type=str, help="Games directory path")
    parser.add_argument(
        "--replay", action="store_true", help="Replay mode: walk through history"
    )
    return parser.parse_args()


def replay_mode(args: argparse.Namespace) -> None:
    """Walk through historical turns of an existing save."""
    from theact.io.save_manager import load_save
    from theact.versioning.git_save import diff_turns, get_history, peek_at_turn

    saves_dir = Path(args.saves_dir) if args.saves_dir else None
    game = load_save(args.save, saves_dir=saves_dir)
    history = get_history(game.save_path)

    if not history:
        print("No turns in history.")
        return

    # History is most-recent-first; reverse for chronological
    history = list(reversed(history))
    idx = 0

    print(f"Save: {args.save} | {len(history)} turns")
    print("Commands: (n)ext, (p)rev, (j)ump <N>, (d)iff <A> <B>, (i)nspect, (q)uit")
    print()

    while True:
        turn_info = history[idx]
        print(f"--- Turn {turn_info.turn} [{turn_info.commit_hash[:8]}] ---")
        print(f"    {turn_info.message}")
        print(f"    {turn_info.timestamp}")
        print()

        try:
            cmd = input("replay> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not cmd or cmd == "n":
            if idx < len(history) - 1:
                idx += 1
            else:
                print("Already at last turn.")
        elif cmd == "p":
            if idx > 0:
                idx -= 1
            else:
                print("Already at first turn.")
        elif cmd.startswith("j"):
            parts = cmd.split()
            if len(parts) == 2 and parts[1].isdigit():
                target = int(parts[1])
                found = False
                for i, h in enumerate(history):
                    if h.turn == target:
                        idx = i
                        found = True
                        break
                if not found:
                    print(f"Turn {target} not found.")
            else:
                print("Usage: j <turn_number>")
        elif cmd.startswith("d"):
            parts = cmd.split()
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                turn_a, turn_b = int(parts[1]), int(parts[2])
                try:
                    diff = diff_turns(game.save_path, turn_a, turn_b)
                    if diff:
                        print(diff)
                    else:
                        print("No differences.")
                except ValueError as e:
                    print(f"Error: {e}")
            else:
                print("Usage: d <turn_a> <turn_b>")
        elif cmd == "i":
            turn_data = peek_at_turn(game.save_path, turn_info.turn)
            for filename, content in sorted(turn_data.items()):
                print(f"\n=== {filename} ===")
                print(content[:500])
                if len(content) > 500:
                    print(f"  ... ({len(content)} chars total)")
        elif cmd == "q":
            break
        else:
            print("Unknown command. Use: n, p, j <N>, d <A> <B>, i, q")
        print()


async def interactive_mode(args: argparse.Namespace) -> None:
    """Step through agents interactively."""
    from theact.debugger import TurnDebugger
    from theact.io.save_manager import create_save
    from theact.llm.config import load_llm_config

    saves_dir = Path(args.saves_dir) if args.saves_dir else None
    games_dir = Path(args.games_dir) if args.games_dir else None

    # Create save if it doesn't exist
    save_path = (saves_dir or Path("saves")) / args.save
    if not save_path.exists():
        if not args.game:
            print("Error: --game required when creating a new save")
            sys.exit(1)
        print(f"Creating save '{args.save}' from game '{args.game}'...")
        create_save(
            args.game,
            args.save,
            "DebugPlayer",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )

    # Get player input
    player_input = args.input
    if not player_input:
        try:
            player_input = input("Player input: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
    if not player_input:
        print("Error: player input cannot be empty")
        sys.exit(1)

    llm_config = load_llm_config()
    debugger = TurnDebugger(
        game_id=args.game or "",
        save_id=args.save,
        player_input=player_input,
        llm_config=llm_config,
        saves_dir=saves_dir,
    )

    pending = debugger.plan_turn()
    print(f"Planned agents: {pending}")
    print()
    print(
        "Commands: (s)tep, (r)eplay <agent>, (e)dit <agent>, "
        "(i)nspect <agent> [field], s(k)ip, (c)ontinue, "
        "ca(p)ture <agent> <name>, com(pa)re <agent>, (q)uit"
    )
    print()

    while True:
        pending = debugger.get_pending()
        if pending:
            print(f"Pending: {pending}")
        else:
            print("All agents complete.")

        try:
            cmd = input("debug> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not cmd:
            continue

        parts = cmd.split()
        action = parts[0].lower()

        if action in ("s", "step"):
            if not pending:
                print("No pending agents.")
                continue
            try:
                step = await debugger.step()
                status = "SKIPPED" if step.skipped else "OK"
                print(f"  [{status}] {step.agent}")
                if not step.skipped:
                    print(f"  Latency: {step.result.latency_ms}ms")
                    print(f"  Content tokens: {step.result.content_tokens}")
                    if step.result.parsed_data:
                        print(f"  Parsed keys: {list(step.result.parsed_data.keys())}")
                    # Show content preview
                    preview = step.result.content[:200]
                    if len(step.result.content) > 200:
                        preview += "..."
                    print(f"  Preview: {preview}")
            except Exception as e:
                print(f"  Error: {e}")

        elif action in ("r", "replay"):
            if len(parts) < 2:
                print("Usage: replay <agent_name>")
                continue
            agent_name = parts[1]
            try:
                step = await debugger.replay(agent_name)
                print(f"  Replayed {agent_name}")
                print(f"  Latency: {step.result.latency_ms}ms")
                preview = step.result.content[:200]
                if len(step.result.content) > 200:
                    preview += "..."
                print(f"  Preview: {preview}")
            except Exception as e:
                print(f"  Error: {e}")

        elif action in ("e", "edit"):
            if len(parts) < 2:
                print("Usage: edit <agent_name>")
                continue
            agent_name = parts[1]
            print("  Edit prompts.py and/or context.py now, then press Enter...")
            try:
                input("  Press Enter when ready: ")
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            try:
                step = await debugger.edit_and_replay(agent_name)
                print(f"  Replayed {agent_name} with reloaded prompts")
                print(f"  Latency: {step.result.latency_ms}ms")
                preview = step.result.content[:200]
                if len(step.result.content) > 200:
                    preview += "..."
                print(f"  Preview: {preview}")
            except Exception as e:
                print(f"  Error: {e}")

        elif action in ("i", "inspect"):
            if len(parts) < 2:
                print("Usage: inspect <agent_name> [field]")
                continue
            agent_name = parts[1]
            field = parts[2] if len(parts) > 2 else "all"
            print(debugger.inspect(agent_name, field))

        elif action in ("k", "skip"):
            skipped = debugger.skip()
            if skipped:
                print(f"  Skipped: {skipped}")
            else:
                print("  Nothing to skip.")

        elif action in ("c", "continue"):
            if not pending:
                print("No pending agents.")
                continue
            try:
                steps = await debugger.run_remaining()
                for step in steps:
                    status = "SKIPPED" if step.skipped else "OK"
                    print(f"  [{status}] {step.agent} ({step.result.latency_ms}ms)")
                print(f"  Ran {len(steps)} agents.")
            except Exception as e:
                print(f"  Error: {e}")

        elif action in ("p", "capture"):
            if len(parts) < 3:
                print("Usage: capture <agent_name> <fixture_name>")
                continue
            agent_name = parts[1]
            fixture_name = parts[2]
            try:
                path = debugger.capture_fixture(agent_name, fixture_name)
                print(f"  Saved to: {path}")
            except Exception as e:
                print(f"  Error: {e}")

        elif action in ("pa", "compare"):
            if len(parts) < 2:
                print("Usage: compare <agent_name>")
                continue
            agent_name = parts[1]
            print(debugger.compare(agent_name))

        elif action in ("q", "quit"):
            break

        else:
            print(
                "Unknown command. Use: step, replay, edit, inspect, "
                "skip, continue, capture, compare, quit"
            )

        print()


def main() -> None:
    args = parse_args()

    if args.replay:
        replay_mode(args)
    else:
        asyncio.run(interactive_mode(args))


if __name__ == "__main__":
    main()
