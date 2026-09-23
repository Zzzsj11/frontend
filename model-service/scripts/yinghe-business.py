"""国内/海外英和：查询余额、查询授权、为指定 Key 增量授权并复核。"""

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public-api"))
from gateway.yinghe_business import BusinessError, YingheBusiness, mask  # noqa: E402


def read_env(path):
    if not path.is_file():
        raise BusinessError("指定的凭据文件不存在")
    result = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            result[name.strip()] = value.strip().strip("\"'")
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True, choices=["yinghe", "yseeai"])
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--business-env-file", type=Path, help="该站点单独的业务凭据文件，可使用 BUSINESS_* 字段")
    parser.add_argument("--target-key-env", help="目标 Key 的环境变量名，不传真实 Key")
    parser.add_argument("--usd-cny", default="6.9", help="美元对人民币参考汇率，默认 6.9")
    parser.add_argument("--dry-run", action="store_true", help="仅打印脱敏计划，不调用接口")
    parser.add_argument("action", choices=["balance", "models", "grant"])
    parser.add_argument("models", nargs="*")
    args = parser.parse_args()
    values = {**read_env(args.env_file), **os.environ}
    prefix = args.channel.upper()
    if args.business_env_file:
        business = read_env(args.business_env_file)
        for suffix in ("USER_ID", "API_KEY", "BASE_URL"):
            name = prefix + "_BUSINESS_" + suffix
            if value := business.get(name) or business.get("BUSINESS_" + suffix):
                values[name] = value
    if args.action == "grant" and not args.models:
        raise BusinessError("grant 必须指定模型编码")
    if args.action != "grant" and args.models:
        raise BusinessError("只有 grant 可以传入模型编码")
    from decimal import Decimal, InvalidOperation

    try:
        rate = Decimal(args.usd_cny)
        if not rate.is_finite() or rate <= 0 or rate > 10000:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise BusinessError("美元汇率必须是正数且不大于 10000") from None
    run_id = "business-cli-" + uuid.uuid4().hex
    api = YingheBusiness(args.channel, target_env=args.target_key_env, values=values, run_id=run_id)
    if args.dry_run:
        result = {"channel": args.channel, "action": args.action, "key_masked": mask(api.target), "models": args.models, "dry_run": True}
    elif args.action == "grant":
        result = await api.grant(args.models)
    elif args.action == "models":
        models = await api.authorized()
        result = {"models": models, "count": len(models), "key_masked": mask(api.target)}
    else:
        result = await api.balance()
        result["currency"] = "USD" if args.channel == "yseeai" else "CNY"
        result["usd_cny"] = format(rate, "f")
        result["cny_balance"] = format(Decimal(result["balance"]) * (rate if args.channel == "yseeai" else 1), "f")
    if args.action == "grant" and not args.dry_run:
        directory = ROOT / ".runtime"
        directory.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(directory / "business-grants.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as journal:
            journal.write(
                json.dumps(
                    {"run_id": run_id, "channel": args.channel, "at": datetime.now(timezone.utc).isoformat(), **result}, ensure_ascii=False
                )
                + "\n"
            )
    print(json.dumps({"channel": args.channel, **result}, ensure_ascii=False, indent=2))
    return 2 if result.get("missing") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except BusinessError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
