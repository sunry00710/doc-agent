from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.core.config import Settings
from app.db.session import create_database_engine
from app.providers.base import ProviderError
from app.providers.factory import build_provider

ROOT = Path(__file__).resolve().parent


def migrate(settings: Settings) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def _backend_command(settings: Settings) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:create_app",
        "--factory",
        "--host",
        settings.backend_host,
        "--port",
        str(settings.backend_port),
    ]


def _worker_command() -> list[str]:
    return [sys.executable, "run_worker.py"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the local Doc Agent backend and worker."
    )
    parser.add_argument("--no-worker", action="store_true")
    parser.add_argument("--no-migrate", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings()
    try:
        build_provider(settings)
    except ProviderError as error:
        raise SystemExit(f"Provider 装配失败：{error}") from error
    if not args.no_migrate:
        migrate(settings)
    processes: list[subprocess.Popen[bytes]] = []
    try:
        backend = subprocess.Popen(_backend_command(settings), cwd=ROOT, env=os.environ.copy())
        processes.append(backend)
        if not args.no_worker:
            worker = subprocess.Popen(
                _worker_command(), cwd=ROOT, env=os.environ.copy()
            )
            processes.append(worker)
        print("Doc Agent services started", flush=True)
        print(f"Backend:  http://{settings.backend_host}:{settings.backend_port}", flush=True)
        print(
            f"Frontend: http://{settings.frontend_host}:{settings.frontend_port} (run `npm --prefix web run dev`)",
            flush=True,
        )
        print("Press Ctrl+C to stop backend and worker.", flush=True)
        while True:
            for process in processes:
                if process.poll() is not None:
                    return process.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        create_database_engine(settings.database_url).dispose()


if __name__ == "__main__":
    raise SystemExit(main())
