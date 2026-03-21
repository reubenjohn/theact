#!/usr/bin/env python
"""Brainstorm game ideas with the LLM.

Usage:
    uv run python scripts/brainstorm.py
    uv run python scripts/brainstorm.py --create  # launch creator after
"""

import argparse
import asyncio

from openai import AsyncOpenAI
from rich.console import Console

from theact.creator.brainstorm import BrainstormSession
from theact.creator.config import load_creator_config

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Brainstorm game ideas")
    parser.add_argument(
        "--create",
        action="store_true",
        help="Launch the game creator after brainstorming",
    )
    args = parser.parse_args()

    config = load_creator_config()
    client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)

    concept = asyncio.run(_run(client, config))

    if concept:
        console.print(f"\n[bold]Concept summary:[/bold]\n{concept}\n")
        if args.create:
            from theact.creator.session import create_game

            asyncio.run(create_game(concept=concept))
    else:
        console.print("[dim]No concept generated.[/dim]")


async def _run(client, config):
    session = BrainstormSession(client, config)
    return await session.run()


if __name__ == "__main__":
    main()
