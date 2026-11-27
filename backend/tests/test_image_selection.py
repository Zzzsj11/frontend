from unittest.mock import AsyncMock


def test_api_preserves_selected_model_despite_legacy_failover(client, monkeypatch):
    import asyncio

    from app.jobs import jobs

    monkeypatch.setattr(jobs, "dispatch", AsyncMock())
    response = client.post("/api/generations/images", json={"prompt": "Synthetic backup test", "model": "nano-banana-2.1-all-in-one", "resolution": "4K", "size": "16:9"})
    assert response.status_code == 202, response.text
    saved = asyncio.run(jobs.get(response.json()["id"]))
    assert saved.request["model"] == "nano-banana-2.1-all-in-one"
    assert saved.request["_providerModelId"] == "nano-banana-2.1"
    assert saved.request["_executionPool"] == "all-in-one:nano-banana-2.1"
    assert saved.request["resolution"] == "4K"
