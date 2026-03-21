"""Entry point for standalone game creation: python -m theact.creator"""

import asyncio

from theact.creator.session import create_game


def main() -> None:
    asyncio.run(create_game())


if __name__ == "__main__":
    main()
