"""Local isolated deployment; does not touch MV services or configuration."""

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

from process_environment import for_service

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
RUNTIME.mkdir(exist_ok=True)
RUNTIME.chmod(0o700)
ENV = ROOT / ".env"


def environment():
    if not ENV.exists():
        ENV.write_text(
            "DATABASE_URL=sqlite+aiosqlite:///"
            + str(RUNTIME / "service.db")
            + "\nADMIN_USERNAME=admin\nADMIN_PASSWORD="
            + secrets.token_urlsafe(24)
            + "\nADMIN_JWT_SECRET="
            + secrets.token_urlsafe(48)
            + "\n"
        )
        ENV.chmod(0o600)
    env = os.environ.copy()
    for line in ENV.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


parser = argparse.ArgumentParser()
parser.add_argument("command", choices=["start", "stop", "status", "migrate"])
args = parser.parse_args()
env = environment()
python = sys.executable
pidfile = RUNTIME / "processes.json"
if args.command == "migrate":
    subprocess.run([python, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"], env=env, cwd=ROOT, check=True)
    subprocess.run([python, str(ROOT / "scripts/seed.py")], env={**env, "PYTHONPATH": str(ROOT / "public-api")}, cwd=ROOT, check=True)
elif args.command == "start":
    if pidfile.exists():
        raise SystemExit("Processes already registered; run status/stop before start")
    subprocess.run([python, __file__, "migrate"], check=True)
    entries = [
        ("public", [python, "-m", "uvicorn", "gateway.main:app", "--host", "127.0.0.1", "--port", "8011"], ROOT / "public-api"),
        ("worker", [python, "-m", "gateway.queue"], ROOT / "public-api"),
        ("admin", [python, "-m", "uvicorn", "control.main:app", "--host", "127.0.0.1", "--port", "8012"], ROOT / "admin-api"),
        ("web", ["npm", "run", "dev"], ROOT / "admin-web"),
        ("user-web", ["npm", "run", "dev"], ROOT / "user-web"),
    ]
    processes = {}
    for name, cmd, cwd in entries:
        with (RUNTIME / (name + ".log")).open("a") as log:
            p = subprocess.Popen(cmd, cwd=cwd, env=for_service(name, env), stdout=log, stderr=log, start_new_session=True)
        processes[name] = p.pid
    pidfile.write_text(json.dumps(processes))
    print("Public API http://127.0.0.1:8011 | Admin http://127.0.0.1:5180 | User http://127.0.0.1:5181")
    print("Local credentials: " + str(ENV))
elif args.command == "stop":
    for pid in json.loads(pidfile.read_text()).values() if pidfile.exists() else []:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    pidfile.unlink(missing_ok=True)
else:
    print(pidfile.read_text() if pidfile.exists() else "Stopped")
