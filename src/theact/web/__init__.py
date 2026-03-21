"""TheAct Web UI -- NiceGUI-based browser interface.

Launch with:
    uv run python -m theact.web
    uv run python -m theact.web --port 8080
"""

from __future__ import annotations


def start_web(
    host: str = "127.0.0.1",
    port: int = 8080,
    reload: bool = False,
) -> None:
    """Launch the NiceGUI web server.

    Args:
        host: Host to bind to.
        port: Port to bind to.
        reload: Enable auto-reload for development.
    """
    from nicegui import ui

    from theact.web.app import setup_app

    setup_app()

    # storage_secret is required for app.storage.user (signs the cookie).
    # For a local-only tool this can be a fixed string.
    ui.run(
        host=host,
        port=port,
        reload=reload,
        title="TheAct",
        dark=True,
        storage_secret="theact-local-secret",
    )
