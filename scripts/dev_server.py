"""Dev server management for TheAct web UI.

Usage:
    uv run scripts/dev_server.py start [--port PORT]
    uv run scripts/dev_server.py stop
    uv run scripts/dev_server.py restart [--port PORT]
    uv run scripts/dev_server.py status
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PIDFILE = Path("/tmp/theact-dev-server.pid")
LOGFILE = Path("/tmp/theact-dev-server.log")
DEFAULT_PORT = 8080


def _kill_theact_web_processes() -> int:
    """Kill any running theact.web processes. Returns count killed."""
    killed = 0
    try:
        out = subprocess.check_output(["pgrep", "-f", "theact.web"], text=True).strip()
    except subprocess.CalledProcessError:
        return 0

    for line in out.splitlines():
        pid = int(line.strip())
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except OSError:
            pass

    if killed:
        time.sleep(1)
    return killed


def _find_process() -> int | None:
    """Return the PID of a running dev server, or None."""
    if not PIDFILE.exists():
        return None
    try:
        pid = int(PIDFILE.read_text().strip())
    except (ValueError, OSError):
        PIDFILE.unlink(missing_ok=True)
        return None
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        PIDFILE.unlink(missing_ok=True)
        return None


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Poll until the server responds on the given port."""
    import urllib.request

    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def cmd_start(port: int) -> None:
    existing = _find_process()
    if existing:
        print(f"Server already running (PID {existing}). Use 'restart' to replace it.")
        return

    proc = subprocess.Popen(
        [sys.executable, "-m", "theact.web", "--port", str(port)],
        stdout=open(LOGFILE, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PIDFILE.write_text(str(proc.pid))

    if _wait_for_server(port):
        print(f"Server started on http://127.0.0.1:{port}/ (PID {proc.pid})")
    else:
        print(f"Server process started (PID {proc.pid}) but not responding yet.")
        print(f"Check logs: {LOGFILE}")


def cmd_stop() -> None:
    pid = _find_process()
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            pass
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.25)
            except OSError:
                break
        PIDFILE.unlink(missing_ok=True)
        print(f"Server stopped (PID {pid}).")
    else:
        # No tracked server — kill any stray theact.web processes
        killed = _kill_theact_web_processes()
        if killed:
            print(f"Killed {killed} stray theact.web process(es).")
        else:
            print("No running server found.")


def cmd_restart(port: int) -> None:
    cmd_stop()
    time.sleep(1)
    cmd_start(port)


def cmd_status() -> None:
    pid = _find_process()
    if pid:
        print(f"Server running (PID {pid}).")
    else:
        print("No running server found.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage TheAct dev web server")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Start the web server")
    p_start.add_argument("--port", type=int, default=DEFAULT_PORT)

    sub.add_parser("stop", help="Stop the web server")

    p_restart = sub.add_parser("restart", help="Restart the web server")
    p_restart.add_argument("--port", type=int, default=DEFAULT_PORT)

    sub.add_parser("status", help="Check if the web server is running")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args.port)
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "restart":
        cmd_restart(args.port)
    elif args.command == "status":
        cmd_status()


if __name__ == "__main__":
    main()
