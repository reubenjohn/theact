"""Fixtures for web UI browser tests.

These tests run against a live NiceGUI server using pytest-playwright.
Run separately from unit tests:  uv run pytest tests/web/
"""

from __future__ import annotations

import multiprocessing
import time

import pytest


def _run_server(host: str, port: int) -> None:
    """Start the NiceGUI server in a subprocess."""
    from theact.web import start_web

    start_web(host=host, port=port)


@pytest.fixture(scope="session")
def web_server():
    """Launch the web UI server for the test session.

    Yields the base URL (e.g. http://127.0.0.1:8090).
    The server runs in a separate process and is torn down after tests.
    """
    host = "127.0.0.1"
    port = 8090
    proc = multiprocessing.Process(target=_run_server, args=(host, port), daemon=True)
    proc.start()

    # Wait for server to be ready
    import urllib.request

    base_url = f"http://{host}:{port}"
    for _ in range(30):
        try:
            urllib.request.urlopen(base_url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("Web server did not start in time")

    yield base_url

    proc.kill()
    proc.join(timeout=5)
