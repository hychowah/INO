#!/usr/bin/env python3
"""Run the local development stack: API, frontend dev server, and Discord bot."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _python_command() -> str:
    return sys.executable


def _launch(name: str, command: list[str], cwd: Path | None = None) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    print(f"[dev-all] starting {name}: {' '.join(command)}")
    return subprocess.Popen(command, cwd=str(cwd or ROOT), creationflags=creationflags)


def _stop_process(name: str, process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    print(f"[dev-all] stopping {name}...")
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=5)
        return
    except Exception:
        pass

    process.terminate()
    try:
        process.wait(timeout=5)
        return
    except Exception:
        pass

    process.kill()
    process.wait(timeout=5)


def _validate_prerequisites() -> None:
    if shutil.which(_npm_command()) is None:
        raise SystemExit("npm is not available on PATH")
    if not FRONTEND_DIR.exists():
        raise SystemExit(f"frontend directory not found: {FRONTEND_DIR}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-bot",
        action="store_true",
        help="Start only the API and frontend dev server.",
    )
    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="Start only Python services without the frontend dev server.",
    )
    args = parser.parse_args()

    _validate_prerequisites()

    processes: list[tuple[str, subprocess.Popen]] = []

    try:
        processes.append(("api", _launch("api", [_python_command(), "api.py"])))

        if not args.no_ui:
            processes.append(
                (
                    "frontend",
                    _launch("frontend", [_npm_command(), "run", "dev"], cwd=FRONTEND_DIR),
                )
            )

        if not args.no_bot:
            processes.append(("bot", _launch("bot", [_python_command(), "bot.py"])))

        print("[dev-all] stack is running")
        print("[dev-all] api:      http://127.0.0.1:8080")
        print("[dev-all] frontend: http://127.0.0.1:5173 (if enabled)")
        print("[dev-all] press Ctrl+C to stop all processes")

        while True:
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    print(f"[dev-all] {name} exited with code {code}")
                    return code
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[dev-all] interrupt received")
        return 0
    finally:
        for name, process in reversed(processes):
            _stop_process(name, process)


if __name__ == "__main__":
    raise SystemExit(main())