from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoEstimatePolicy:
    provider: str
    unit_price_per_second: float
    balance_check: bool = True
    billing_mode: str = "estimated"

    def capability(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "unitPricePerSecond": self.unit_price_per_second,
            "balanceCheck": self.balance_check,
            "billingMode": self.billing_mode,
            "currency": "CNY",
        }


VIDEO_ESTIMATE_POLICIES = {
    "doubao-seedance-2.0": VideoEstimatePolicy("yinghe", 0.83),
    "doubao-seedance-2.0-mini": VideoEstimatePolicy("yinghe", 0.50),
    "doubao-seedance-2.0-fast": VideoEstimatePolicy("yinghe", 0.80),
    "wan3.0-video": VideoEstimatePolicy("yinghe", 0.60),
    "wan3.0-video-prime": VideoEstimatePolicy("yinghe", 0.90),
    "kling-v3": VideoEstimatePolicy("yinghe", 0.80),
    # 海外站尚未提供人民币结算表。这里按 Google 公布的美元标价、以 7.2 CNY/USD
    # 做生成前保守预估；不查询国内英和余额，最终对账保持 unpriced，等待供应商报价。
    "veo-3.1-generate-preview": VideoEstimatePolicy("yseeai", 2.88, balance_check=False, billing_mode="official_usd_estimate"),
    "veo-3.1-fast-generate-preview": VideoEstimatePolicy("yseeai", 0.72, balance_check=False, billing_mode="official_usd_estimate"),
    "gemini-omni-flash-preview": VideoEstimatePolicy("yseeai", 0.72, balance_check=False, billing_mode="official_usd_estimate"),
    # ToAPIs 当前 Key 的 720p 目录价为 $0.01912/秒，按 7.2 CNY/USD 粗估。
    "grok-video-1.5": VideoEstimatePolicy("toapis", 0.137664, balance_check=False, billing_mode="supplier_usd_estimate"),
    "minimax-h3": VideoEstimatePolicy("yinghe", 0.425),
    "doubao-seedance-2.0-ppio": VideoEstimatePolicy("ppio", 0.8),
    "minimax-h3-ppio": VideoEstimatePolicy("ppio", 0.425),
    "minimax-h3-runninghub": VideoEstimatePolicy("runninghub", 0, balance_check=False, billing_mode="excluded"),
}


def video_estimate_policy(model: str) -> VideoEstimatePolicy:
    return VIDEO_ESTIMATE_POLICIES.get(model, VideoEstimatePolicy("yinghe", 0.83))
