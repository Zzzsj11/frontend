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
    "minimax-h3": VideoEstimatePolicy("yinghe", 0.425),
    "doubao-seedance-2.0-ppio": VideoEstimatePolicy("ppio", 0.8),
    "minimax-h3-ppio": VideoEstimatePolicy("ppio", 0.425),
    "minimax-h3-runninghub": VideoEstimatePolicy("runninghub", 0, balance_check=False, billing_mode="excluded"),
}


def video_estimate_policy(model: str) -> VideoEstimatePolicy:
    return VIDEO_ESTIMATE_POLICIES.get(model, VideoEstimatePolicy("yinghe", 0.83))
