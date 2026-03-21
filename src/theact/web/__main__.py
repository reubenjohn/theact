"""Entry point for `python -m theact.web`.

Usage:
    uv run python -m theact.web
    uv run python -m theact.web --port 8080
    uv run python -m theact.web --host 0.0.0.0 --port 8080
"""

import argparse


def main() -> None:
    """Parse CLI args and launch the web server."""
    parser = argparse.ArgumentParser(description="Launch TheAct Web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )
    args = parser.parse_args()

    from theact.web import start_web

    start_web(host=args.host, port=args.port, reload=args.reload)


main()
