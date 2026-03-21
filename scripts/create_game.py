"""Interactive game creation script.

Usage:
    uv run python scripts/create_game.py
"""

import asyncio

from dotenv import load_dotenv

from theact.creator.session import create_game


def main() -> None:
    load_dotenv()
    result = asyncio.run(create_game())
    if result:
        print(f"\nGame files written to: {result}")
    else:
        print("\nGame creation aborted or failed.")


if __name__ == "__main__":
    main()
