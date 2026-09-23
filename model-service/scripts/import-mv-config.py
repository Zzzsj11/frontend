"""Explicit operator tool: import model credentials without printing them.
Use --local for local MV settings, or --ssh HOST with SSH config/proxy already configured.
Never runs generation or modifies the source installation.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--local", action="store_true")
parser.add_argument("--ssh")
parser.add_argument("--proxy-command")
args = parser.parse_args()
script = """import json
from app.config import settings as s
pairs={
'YINGHE_BASE_URL':s.video_api_base_url,'YINGHE_API_KEY':s.video_api_key,
'YINGHE_LLM_BASE_URL':s.llm_base_url.removesuffix('/v1'),'YINGHE_LLM_API_KEY':s.llm_api_key,
'YSEEAI_BASE_URL':s.yseeai_api_base_url,'YSEEAI_API_KEY':s.yseeai_api_key,
'TOAPIS_BASE_URL':s.toapis_api_base_url,'TOAPIS_API_KEY':s.toapis_api_key,
'RUNNINGHUB_BASE_URL':s.runninghub_base_url.removesuffix('/openapi/v2'),'RUNNINGHUB_API_KEY':s.runninghub_api_key,
'OPTIMIZER_GEMINI_BASE_URL':s.prompt_optimizer_gemini_base_url.removesuffix('/v1'),'OPTIMIZER_GEMINI_API_KEY':s.prompt_optimizer_gemini_api_key,
'OPTIMIZER_MINIMAX_BASE_URL':s.prompt_optimizer_minimax_base_url,'OPTIMIZER_MINIMAX_API_KEY':s.prompt_optimizer_minimax_api_key,
'YINGHE_ASSET_GROUP_ID':s.aigc_asset_group_id,'LLM_MODEL':s.llm_model,
'TOS_ACCESS_KEY':s.tos_access_key,'TOS_SECRET_KEY':s.tos_secret_key,'TOS_ENDPOINT':s.tos_endpoint,'TOS_REGION':s.tos_region,
'TOS_REFERENCE_BUCKET':s.tos_reference_bucket,'TOS_VIDEO_BUCKET':s.tos_video_bucket}
assert s.image_api_key == s.video_api_key, 'Image and video keys differ; configure separate channels before importing'
print(json.dumps(pairs))
"""
if args.local:
    result = subprocess.run([sys.executable, "-c", script], cwd=root.parent / "backend", capture_output=True, text=True, check=True)
elif args.ssh:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "KexAlgorithms=ecdh-sha2-nistp256",
        "-o",
        "HostKeyAlgorithms=ssh-ed25519",
        "-o",
        "Ciphers=aes128-gcm@openssh.com",
    ]
    if args.proxy_command:
        cmd += ["-o", "ProxyCommand=" + args.proxy_command]
    result = subprocess.run(
        cmd + [args.ssh, "docker exec -i mv-agent-frontend-backend-1 python -"], input=script, capture_output=True, text=True, check=True
    )
else:
    parser.error("Choose --local or --ssh")
values = json.loads(result.stdout)
path = root / ".env"
existing = dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#") and "=" in line)
existing.update(values)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    for k, v in existing.items():
        if "\n" in str(v):
            raise ValueError("Multiline config not supported")
        f.write(f"{k}={v}\n")
path.chmod(0o600)
private = root / ".secrets"
private.mkdir(exist_ok=True)
private.chmod(0o700)
connection = private / "connections.md"
connection.write_text(
    "# Internal connection credentials — do not share or commit\n\n"
    + "\n".join(f"- `{k}`: `{v}`" for k, v in values.items() if not k.startswith("TOS_"))
    + "\n"
)
connection.chmod(0o600)
print("Imported configured channels to private .env; supplier credentials saved in .secrets/connections.md")
