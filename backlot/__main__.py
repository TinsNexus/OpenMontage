"""Backlot CLI.

    python -m backlot open [project-id]   # start server if needed, open browser
    python -m backlot serve [--port N]    # run the server in the foreground

``open`` is idempotent and non-fatal by design: agents call it at pipeline
initialization and must continue the production even if it fails.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

from backlot import DEFAULT_PORT


def _port() -> int:
    try:
        return int(os.environ.get("BACKLOT_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def _health(port: int) -> dict | None:
    """The running server's /api/health body, or None when nothing answers."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as resp:
            if resp.status != 200:
                return None
            import json

            body = json.loads(resp.read().decode("utf-8") or "{}")
            return body if isinstance(body, dict) and body.get("app") == "backlot" else None
    except Exception:
        return None


def _server_alive(port: int) -> bool:
    return _health(port) is not None


def _stop_server(port: int) -> bool:
    """Stop the Backlot server on this port (only if it identifies as Backlot)."""
    import signal

    info = _health(port)
    pid = (info or {}).get("pid")
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.time() + 10
    while time.time() < deadline and _server_alive(port):
        time.sleep(0.3)
    return not _server_alive(port)


def _ensure_server(port: int) -> bool:
    """Start the server if needed; restart it when it runs older code than disk."""
    info = _health(port)
    if info is not None and info.get("stale"):
        print("backlot: server is running older code — restarting it")
        if not _stop_server(port):
            print("backlot: could not stop the old server; stop it manually and retry")
            return False
        info = None
    if info is not None:
        return True
    try:
        _spawn_server(port)
    except Exception as exc:
        print(f"backlot: could not start server ({exc})")
        return False
    deadline = time.time() + 15
    while time.time() < deadline:
        if _server_alive(port):
            return True
        time.sleep(0.4)
    print("backlot: server did not come up in time")
    return False


def _spawn_server(port: int) -> None:
    """Start the server as a detached background process."""
    cmd = [sys.executable, "-m", "backlot", "serve", "--port", str(port)]
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def cmd_open(project_id: str | None) -> int:
    port = _port()
    if not _ensure_server(port):
        print("backlot: continuing without the board")
        return 1
    url = f"http://127.0.0.1:{port}/"
    if project_id:
        url = f"http://127.0.0.1:{port}/p/{project_id}"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"backlot: {url}")
    return 0


def cmd_serve(port: int) -> int:
    import uvicorn

    uvicorn.run("backlot.server:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


def cmd_restart(port: int) -> int:
    """Stop the running server (if any) and start a fresh one in the background."""
    if _server_alive(port) and not _stop_server(port):
        print(f"backlot: could not stop the server on port {port}")
        return 1
    _spawn_server(port)
    deadline = time.time() + 15
    while time.time() < deadline:
        if _server_alive(port):
            print(f"backlot: restarted at http://127.0.0.1:{port}/")
            return 0
        time.sleep(0.4)
    print("backlot: server did not come up in time")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backlot", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    p_open = sub.add_parser("open", help="open the board in the browser (starts server if needed)")
    p_open.add_argument("project_id", nargs="?", default=None)

    p_serve = sub.add_parser("serve", help="run the Backlot server in the foreground")
    p_serve.add_argument("--port", type=int, default=_port())

    p_restart = sub.add_parser("restart", help="restart the background server (e.g. after updating Backlot)")
    p_restart.add_argument("--port", type=int, default=_port())

    args = parser.parse_args(argv)
    if args.command == "open":
        return cmd_open(args.project_id)
    if args.command == "serve":
        return cmd_serve(args.port)
    if args.command == "restart":
        return cmd_restart(args.port)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
