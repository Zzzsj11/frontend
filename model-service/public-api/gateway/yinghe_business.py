"""国内、海外英和业务 API；调用 Key 与商户签名密钥严格分离。"""

import hashlib
import os
import re
import time
from decimal import Decimal

import httpx

BASES = {"yinghe": "https://api-aigc.fzyinghe.com", "yseeai": "https://api-aigc.yseeai.com"}


class BusinessError(ValueError):
    pass


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Invalid amount")
    return format(result, "f")


def mask(value):
    return value[:7] + "…" + value[-4:] if len(value) > 12 else "***"


def sign(fields, secret):
    raw = "&".join(f"{key}={fields[key]}" for key in sorted(fields) if fields[key] not in (None, ""))
    return hashlib.md5((raw + "&key=" + secret).encode()).hexdigest().upper()


class YingheBusiness:
    def __init__(self, channel, target_env=None, values=None, transport=None, run_id=None):
        if channel not in BASES:
            raise BusinessError("仅支持英和国内 yinghe 和海外 yseeai")
        values = os.environ if values is None else values
        prefix = channel.upper()
        self.base = values.get(prefix + "_BUSINESS_BASE_URL", BASES[channel]).rstrip("/")
        # 凭据只发送到该站点的官方业务域名，禁止跨国内/海外复用。
        if self.base != BASES[channel]:
            raise BusinessError("业务域名必须与所选英和站点一致")
        self.user_id = values.get(prefix + "_BUSINESS_USER_ID", "")
        self.secret = values.get(prefix + "_BUSINESS_API_KEY", "")
        self.target = values.get(target_env or prefix + "_API_KEY", "")
        if not self.user_id or not self.secret or not self.target:
            raise BusinessError("缺少该渠道的商户 ID、业务签名密钥或目标调用 Key")
        self.transport, self.run_id = transport, run_id

    async def post(self, path, **extra):
        fields = {"userId": self.user_id, "timestamp": int(time.time()), **extra}
        payload = {**fields, "sign": sign(fields, self.secret)}
        if self.user_id.isdigit():
            payload["userId"] = int(self.user_id)
        headers = {}
        if self.run_id:
            headers = {"X-Agent-Name": "code-agent", "X-Agent-Run-Id": self.run_id, "X-Test-Run-Id": self.run_id}
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=self.transport) as client:
                response = await client.post(self.base + path, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
            if not isinstance(body, dict) or body.get("code") != 200 or not isinstance(body.get("data"), (dict, type(None))):
                raise BusinessError("业务接口拒绝请求，请核对商户归属、权限或限流；未自动重试")
            return body.get("data") or {}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            if isinstance(exc, BusinessError):
                raise
            raise BusinessError("业务接口请求失败或响应无效；未自动重试") from None

    async def authorized(self):
        data = await self.post("/business/tokens/authorizedModels", apiKey=self.target)
        models = data.get("models")
        if not isinstance(models, list) or any(not isinstance(x, str) for x in models):
            raise BusinessError("授权模型响应格式错误")
        return sorted(set(models))

    async def balance(self):
        data = await self.post("/business/reconcile/balance")
        try:
            amount = number(data["balance"])
        except (KeyError, ValueError, ArithmeticError):
            raise BusinessError("余额响应缺少有效金额") from None
        result = {"balance": amount, "key_masked": mask(self.target), "quota": None, "quota_error": None}
        try:
            result["quota"] = await self.quota()
        except BusinessError as exc:
            result["quota_error"] = str(exc)
        return result

    async def quota(self):
        for page in range(1, 21):
            data = await self.post("/business/tokens/list", pageNum=page, pageSize=100)
            items = data.get("list")
            if not isinstance(items, list):
                raise BusinessError("Key 额度响应格式错误")
            for item in items:
                if not isinstance(item, dict) or item.get("apiKey") != self.target:
                    continue
                try:
                    quota = number(item["quotaAmt"]) if item.get("quotaAmt") is not None else None
                    used = number(item.get("usedAmt") or 0)
                    return {
                        "name": str(item.get("name") or ""),
                        "limit": quota,
                        "used": used,
                        "remaining": number(Decimal(quota) - Decimal(used)) if quota is not None else None,
                        "unlimited": quota is None,
                    }
                except (ValueError, ArithmeticError):
                    raise BusinessError("Key 额度不是有效金额") from None
            if len(items) < 100:
                break
        raise BusinessError("目标 Key 未在该商户额度列表中找到")

    async def grant(self, models):
        requested = list(dict.fromkeys(models))
        if not requested or len(requested) > 200 or any(not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", x) for x in requested):
            raise BusinessError("模型编码为空、数量过多或格式无效")
        # 先验证商户确实可以管理这个 Key；仅补差集，永不全量覆盖。
        before = set(await self.authorized())
        pending = [x for x in requested if x not in before]
        results = []
        for model in pending:
            try:
                await self.post("/business/tokens/addModel", apiKey=self.target, model=model)
                results.append({"model": model, "submitted": True})
            except BusinessError as exc:
                results.append({"model": model, "submitted": False, "error": str(exc)})
                break  # 超时/限流立即停止；再次执行时先复核，避免盲目重放。
        after = set(await self.authorized())
        return {
            "key_masked": mask(self.target),
            "requested": requested,
            "added": sorted(after - before),
            "already_authorized": sorted(set(requested) & before),
            "missing": sorted(set(requested) - after),
            "results": results,
            "authorized_count": len(after),
        }
