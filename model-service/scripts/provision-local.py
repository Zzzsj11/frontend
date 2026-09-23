"""Create local internal client credentials once; never print secret values."""

import json
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
env = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line and not line.startswith("#"))
private = root / ".secrets"
private.mkdir(exist_ok=True)
private.chmod(0o700)
path = private / "clients.json"
if not path.exists():
    with httpx.Client(base_url="http://127.0.0.1:8012", timeout=30) as client:
        response = client.post("/admin/login", json={"username": env["ADMIN_USERNAME"], "password": env["ADMIN_PASSWORD"]})
        response.raise_for_status()
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        clients = {}
        for name, test in [("mv-system", False), ("code-agent-acceptance", True)]:
            response = client.post("/admin/clients", json={"name": name, "require_agent": test, "concurrency": 4})
            response.raise_for_status()
            clients[name] = response.json()
    path.write_text(json.dumps(clients, indent=2))
    path.chmod(0o600)
clients = json.loads(path.read_text())
doc = private / "API-INTEGRATION.internal.md"
doc.write_text(
    (root / "docs/API-INTEGRATION.md").read_text()
    + "\n\n# 本机实际连接凭据（仅公司内部）\n\n"
    + "管理后台用户名：`"
    + env["ADMIN_USERNAME"]
    + "`\n\n管理后台密码：`"
    + env["ADMIN_PASSWORD"]
    + "`\n\n"
    + "\n".join("- " + name + " 内部 API Key：`" + c["api_key"] + "`" for name, c in clients.items())
    + "\n\n"
    + (private / "connections.md").read_text()
)
doc.chmod(0o600)
print("Internal credential document written with mode 600")
