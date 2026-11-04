"""Disposable local dependencies; never use business databases or global pruning."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "backend/.venv/bin/python"


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def remove_build_images(project):
    for service in ("backend", "frontend"):
        tag = f"local/{project}-{service}:proof"
        result = subprocess.run(
            ["docker", "image", "rm", tag], check=False, capture_output=True, text=True
        )
        if result.returncode and "no such image" not in result.stderr.lower():
            raise RuntimeError(f"Could not remove this run's image: {tag}")


def overlay(project):
    return f"""services:
  postgres:
    restart: 'no'
    environment:
      POSTGRES_DB: mv_local_proof
      POSTGRES_USER: mv_local_proof
      POSTGRES_PASSWORD: synthetic-{project}
    ports: !override ['127.0.0.1::5432']
    volumes: !reset []
    tmpfs: ['/var/lib/postgresql/data:size=512m']
  redis:
    restart: 'no'
    command: ['redis-server', '--save', '', '--appendonly', 'no']
    ports: !override ['127.0.0.1::6379']
    volumes: !reset []
    tmpfs: ['/data:size=64m']
  backend:
    image: local/{project}-backend:proof
  frontend:
    image: local/{project}-frontend:proof
"""


def environment(project, postgres_port, redis_port=None):
    # Explicit values prevent backend/.env from supplying a business DB or Key.
    return {
        **os.environ,
        "APP_ENV": "development",
        "RUNTIME_SECRETS_FILE": "/nonexistent/mv-local-runtime-secrets",
        "DATABASE_URL": f"postgresql+asyncpg://mv_local_proof:synthetic-{project}@127.0.0.1:{postgres_port}/mv_local_proof",
        "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0"
        if redis_port
        else "fakeredis://",
        "JWT_SECRET": "synthetic-local-verification-secret-at-least-32-bytes",
        "LLM_CHANNEL": "",
        "LLM_API_KEY": "synthetic-only",
        "AIGC_TOKEN": "synthetic-only",
        "ALL_IN_ONE_BASE_URL": "https://mg-test.epaipix.com",
        "ALL_IN_ONE_API_KEY": "",
        "REFRESH_COOKIE_SECURE": "false",
        "JOB_EXECUTION_MODE": "inline",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(ROOT / "backend"),
    }


@contextmanager
def dependencies(*, redis=True, build=False, runner=run):
    project = "mv-local-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=project + "-") as directory:
        override = Path(directory) / "compose.yml"
        override.write_text(overlay(project))
        compose = [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            ROOT / "docker-compose.yml",
            "-f",
            ROOT / "docker-compose.local-build.yml",
            "-f",
            override,
        ]
        print(
            f"Local run: {project}; temporary resources are removed on exit", flush=True
        )
        try:
            if build:
                runner([*compose, "build", "backend", "frontend"], cwd=ROOT)
                yield {}
            else:
                services = ["postgres", "redis"] if redis else ["postgres"]
                runner(
                    [
                        *compose,
                        "up",
                        "-d",
                        "--no-deps",
                        "--wait",
                        "--wait-timeout",
                        "90",
                        *services,
                    ],
                    cwd=ROOT,
                )

                def port(service, internal):
                    result = runner(
                        [*compose, "port", service, str(internal)],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                    )
                    address, published = result.stdout.strip().rsplit(":", 1)
                    if address != "127.0.0.1" or not published.isdigit():
                        raise RuntimeError(
                            "Temporary services must bind only to loopback"
                        )
                    return int(published)

                yield environment(
                    project,
                    port("postgres", 5432),
                    port("redis", 6379) if redis else None,
                )
        finally:
            # This project name is generated here, never accepted from user input.
            try:
                runner(
                    [
                        *compose,
                        "down",
                        "--volumes",
                        "--remove-orphans",
                        "--timeout",
                        "10",
                    ],
                    cwd=ROOT,
                )
            finally:
                if build:
                    # Even a failed down must attempt this run's image cleanup.
                    remove_build_images(project)
            print(f"Cleaned local run: {project}", flush=True)


def migrate(env):
    run([PYTHON, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", env=env)


def develop(env):
    children = []
    try:
        for args, cwd in (
            (
                [
                    PYTHON,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                ROOT / "backend",
            ),
            (
                [
                    "npm",
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "5173",
                    "--strictPort",
                ],
                ROOT,
            ),
        ):
            children.append(
                subprocess.Popen(
                    [str(a) for a in args], cwd=cwd, env=env, start_new_session=True
                )
            )
        print(
            "Temporary local app: http://127.0.0.1:5173; Ctrl-C removes its services and data. Model Keys are disabled.",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.2)
        for child in children:
            if child.poll() is not None and child.returncode:
                raise subprocess.CalledProcessError(child.returncode, child.args)
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=["heads", "migration", "middleware", "dev", "build"]
    )
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    if args.mode == "heads":
        output = run(
            [PYTHON, "-m", "alembic", "heads"],
            cwd=ROOT / "backend",
            capture_output=True,
            text=True,
        ).stdout
        if len(output.strip().splitlines()) != 1 or "(head)" not in output:
            raise RuntimeError("Alembic must have exactly one head")
        print(output.strip())
        return
    with dependencies(
        redis=args.mode in {"middleware", "dev"}, build=args.mode == "build"
    ) as env:
        if args.mode == "build":
            return
        migrate(env)
        if args.mode == "middleware":
            run([PYTHON, ROOT / "scripts/local_middleware_proof.py"], cwd=ROOT, env=env)
        elif args.mode == "dev":
            develop(env)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
