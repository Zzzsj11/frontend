#!/usr/bin/env python3
"""查询/对比 AIGC 平台 API Key 已开通的模型列表（上游 OpenAI 风格 GET /v1/models）。

用法：
  python3 scripts/check-aigc-models.py                      # 查 backend/.env 当前 key
  python3 scripts/check-aigc-models.py --key yh-xxx         # 查指定 key
  python3 scripts/check-aigc-models.py --key yh-xxx --compare  # 与 .env 当前 key 对比
  python3 scripts/check-aigc-models.py --key yh-a --key yh-b   # 两个 key 互相对比
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://api-aigc.fzyinghe.com"
# .env 中查找 key 的优先级，与后端 providers.py 的读取顺序保持一致
ENV_KEY_CANDIDATES = ("VIDEO_API_KEY", "IMAGE_API_KEY", "AIGC_TOKEN")
ENV_FILE = Path(__file__).resolve().parent.parent / "backend" / ".env"


def mask(key: str) -> str:
    return key if len(key) <= 10 else f"{key[:7]}...{key[-4:]}"


def key_from_env(env_file: Path = ENV_FILE) -> tuple[str, str] | None:
    if not env_file.exists():
        return None
    values: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip().strip("'\"")
    for name in ENV_KEY_CANDIDATES:
        if values.get(name):
            return name, values[name]
    return None


def fetch_models(base_url: str, key: str) -> list[str]:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    data = body.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"模型列表接口未返回 data 数组：{str(body)[:200]}")
    return sorted(str(item.get("id", "?")) for item in data if isinstance(item, dict))


def print_models(label: str, models: list[str]) -> None:
    print(f"{label}（共 {len(models)} 个模型）")
    for model in models:
        print(f"  - {model}")


def compare(label_a: str, models_a: list[str], label_b: str, models_b: list[str]) -> None:
    only_a = sorted(set(models_a) - set(models_b))
    only_b = sorted(set(models_b) - set(models_a))
    print(f"对比 {label_a} vs {label_b}：")
    print(f"  仅 {label_a} 有：{', '.join(only_a) if only_a else '无'}")
    print(f"  仅 {label_b} 有：{', '.join(only_b) if only_b else '无'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="查询/对比 AIGC 平台 API Key 已开通的模型列表")
    parser.add_argument("--key", action="append", default=[], help="要查询的 API Key，可多次传入")
    parser.add_argument("--compare", action="store_true", help="将 --key 与 backend/.env 当前 key 对比")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"接入域名，默认 {DEFAULT_BASE_URL}")
    parser.add_argument("--show-key", action="store_true", help="输出中显示完整 key（默认脱敏）")
    args = parser.parse_args()

    show = (lambda k: k) if args.show_key else mask
    targets: list[tuple[str, str]] = [("传入 key", k) for k in args.key]

    env_entry = key_from_env()
    if not targets or args.compare:
        if not env_entry:
            print(f"未在 {ENV_FILE} 找到 {'/'.join(ENV_KEY_CANDIDATES)}", file=sys.stderr)
            return 1
        env_name, env_key = env_entry
        targets.insert(0, (f".env 当前 key（{env_name}）", env_key))

    results: list[tuple[str, list[str]]] = []
    for label, key in targets:
        try:
            models = fetch_models(args.base_url, key)
        except Exception as exc:
            print(f"{label} {show(key)} 查询失败：{exc}", file=sys.stderr)
            return 1
        print_models(f"{label} {show(key)}", models)
        if not models:
            # 上游对无效 key 也返回 200 + 空列表，需单独提示
            print(f"  警告：模型列表为空，key 可能无效或未开通任何模型", file=sys.stderr)
            return 2
        results.append((label, models))

    if len(results) == 2:
        print()
        compare(results[0][0], results[0][1], results[1][0], results[1][1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
