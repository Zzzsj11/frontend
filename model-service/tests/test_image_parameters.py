from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_toapis_image_parameters():
    from gateway.image_parameters import toapis_image
    from gateway.schemas import ImageCreate

    model = SimpleNamespace(provider_model="gpt-image-2.5-flare")
    for size, ratio, tier in [("1024x1536", "2:3", "1K"), ("2048x2048", "1:1", "2K"), ("2880x2880", "1:1", "4K")]:
        result = toapis_image(model, ImageCreate(model="test", prompt="test", size=size, images=["https://example.test/a.png"]))
        assert (result["size"], result["resolution"], result["quality"]) == (ratio, tier, "high")
        assert result["reference_images"] == ["https://example.test/a.png"]
    for changes in ({"quality": "medium"}, {"size": "1234x2345"}, {"size": "2048x2048", "resolution": "1K"}):
        with pytest.raises(HTTPException) as exc:
            toapis_image(model, ImageCreate(model="test", prompt="test", **changes))
        assert exc.value.status_code == 422
    seed = SimpleNamespace(provider_model="doubao-seedream-5-0")
    result = toapis_image(seed, ImageCreate(model="test", prompt="test", size="9:16", resolution="3K"))
    assert result["size"] == "9:16" and result["metadata"]["resolution"] == "3K"
    with pytest.raises(HTTPException):
        toapis_image(seed, ImageCreate(model="test", prompt="test", size="1:1", resolution="4K"))


async def test_image_quote_and_job_share_parameters(service, monkeypatch):
    from gateway.db import Job, Model, ModelRoute, Session

    api, _, _, _ = service
    monkeypatch.setenv("TOAPIS_API_KEY", "synthetic")
    async with Session.begin() as db:
        m = await db.get(Model, "gpt-image-2.5-flare")
        m.capabilities = {"unified_catalog": True}
        db.add(
            ModelRoute(
                id="image-route",
                model_id=m.id,
                supplier="toapis",
                channel="toapis",
                provider_model=m.id,
                protocol="toapis-image",
                enabled=True,
                priority=1,
                concurrency=2,
                verification="passed",
                capabilities={},
                pricing={
                    "estimate_rules": [
                        {
                            "confirmed": True,
                            "conditions": {"resolution": "4K", "quality": "high"},
                            "rates": [{"label": "images", "path": "requests", "cny": "2", "unit": "1"}],
                        }
                    ]
                },
            )
        )
    body = {"model": "gpt-image-2.5-flare", "prompt": "test", "size": "2880x2880"}
    quote = await api.post("/v1/images", json={**body, "estimate_only": True})
    assert quote.status_code == 200, quote.text
    assert quote.json()["status"] == "estimated"
    response = await api.post("/v1/images", json=body)
    assert response.status_code == 202, response.text
    async with Session() as db:
        job = await db.get(Job, response.json()["id"])
        assert {k: job.payload[k] for k in ("size", "resolution", "quality")} == quote.json()["normalized_parameters"]
    rejected = await api.post("/v1/images", json={**body, "quality": "medium"}, headers={"Idempotency-Key": "invalid"})
    assert rejected.status_code == 422
