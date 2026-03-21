"""Rich terminal CLI for TheAct."""

import asyncio

from theact.cli.app import Application


def main() -> None:
    """Entry point: run the CLI application."""
    app = Application()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass


__all__ = ["Application", "main"]
