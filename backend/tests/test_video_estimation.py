from app.video_estimation import video_estimate_policy


def test_new_yinghe_video_model_estimates_are_explicit():
    expected = {
        "doubao-seedance-2.0-mini": 0.50,
        "doubao-seedance-2.0-fast": 0.80,
        "wan3.0-video": 0.60,
        "wan3.0-video-prime": 0.90,
        "kling-v3": 0.80,
    }

    for model_id, unit_price in expected.items():
        policy = video_estimate_policy(model_id)
        assert policy.provider == "yinghe"
        assert policy.unit_price_per_second == unit_price
        assert policy.balance_check is True
        assert policy.billing_mode == "estimated"
