import importlib
from decimal import Decimal
from types import SimpleNamespace


def test_real_nested_usage_preserved_and_not_double_counted(service):
    normalize = importlib.import_module("gateway.usage_normalization").normalize_usage
    original = {"rawUsage": {"input_tokens": 41, "output_tokens": 6144, "cached_tokens": 0, "input_tokens_details": {"image_tokens": 0}}}
    result = normalize(original)
    assert result["input_tokens"] == 41 and result["output_tokens"] == 6144
    assert result["rawUsage"] == original["rawUsage"]
    assert "image_tokens" not in result and "input_tokens" not in original
    assert normalize({"prompt_tokens": 0, "completion_tokens": 3})["input_tokens"] == 0
    assert normalize({"input_tokens": None, "prompt_tokens": 10})["input_tokens"] is None
    assert normalize({"billing": {"status": "pending"}}) == {"billing": {"status": "pending"}}


def test_unknown_cache_subtraction_never_becomes_zero(service):
    credits = importlib.import_module("gateway.credits")
    job = SimpleNamespace(
        usage={"input_tokens": 100},
        pricing_snapshot={
            "confirmed": True,
            "rates": [{"label": "input", "path": "input_tokens", "subtract": ["cache.read"], "unit": "100", "cny": "1"}],
        },
    )
    assert credits.measured_points(job) is None
    job.usage["cache"] = {"read": None}
    assert credits.measured_points(job) is None
    job.usage["cache"]["read"] = 0
    assert credits.measured_points(job)[0] == Decimal("100")
    job.usage["cache"]["read"] = 40
    assert credits.measured_points(job)[0] == Decimal("60")


def test_settled_video_generation_usage_is_extracted(service):
    usage = importlib.import_module("gateway.queue").usage
    result = usage(
        {
            "generation": {"usage": {"completion_tokens": 87300, "total_tokens": 87300}},
            "billing": {"status": "settled", "credits": "174.6", "cost_usd": "0.873"},
        }
    )
    assert result["total_tokens"] == 87300
    assert result["output_tokens"] == 87300
    assert result["billing"]["credits"] == "174.6"
    assert "input_tokens" not in result
