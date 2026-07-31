"""Run the local API and TypeScript workbench as one interruptible demo."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=4173)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    return parser.parse_args()


def wait_for_health(url: str, process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"API exited before becoming healthy (exit {process.returncode})")
        try:
            with urllib.request.urlopen(url, timeout=0.8) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise TimeoutError(f"API did not become healthy within {timeout:.0f}s")


def terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    args = parse_args()
    repository = Path(__file__).resolve().parents[1]
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required; install Node.js 20 or newer")

    environment = os.environ.copy()
    environment["MVS_DATA_DIR"] = str((repository / args.data_dir).resolve())
    api_command = [
        sys.executable,
        "-m",
        "uvicorn",
        "manufacturing_vision_studio.api:create_app",
        "--factory",
        "--host",
        args.host,
        "--port",
        str(args.api_port),
    ]
    web_command = [
        npm,
        "--prefix",
        "web",
        "run",
        "dev",
        "--",
        "--host",
        args.host,
        "--port",
        str(args.web_port),
    ]

    api = subprocess.Popen(api_command, cwd=repository, env=environment)
    web: subprocess.Popen[bytes] | None = None

    def stop_children(_signum: int | None = None, _frame: object | None = None) -> None:
        if web is not None:
            terminate(web)
        terminate(api)

    signal.signal(signal.SIGINT, stop_children)
    signal.signal(signal.SIGTERM, stop_children)

    try:
        wait_for_health(f"http://{args.host}:{args.api_port}/api/health", api)
        web = subprocess.Popen(web_command, cwd=repository, env=environment)
        print(
            f"\nManufacturing Vision Studio is starting at "
            f"http://{args.host}:{args.web_port}\n"
            "Synthetic demo only; press Ctrl-C to stop both local services.\n",
            flush=True,
        )
        while api.poll() is None and web.poll() is None:
            time.sleep(0.25)
        return api.returncode if api.returncode is not None else (web.returncode or 0)
    finally:
        stop_children()


if __name__ == "__main__":
    raise SystemExit(main())
