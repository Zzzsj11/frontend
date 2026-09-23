import httpx
import pytest


@pytest.mark.asyncio
async def test_supplier_route_frozen_and_user_cannot_override(service, monkeypatch):
    from gateway.db import Job, Model, ModelRoute, Session
    from sqlalchemy import select

    api, ctl, _, _ = service
    async with Session.begin() as db:
        m = await db.get(Model, "gpt-5.6-sol")
        m.capabilities = {"unified_catalog": True}
        db.add(
            ModelRoute(
                id="test-route",
                model_id=m.id,
                supplier="yseeai",
                channel="yseeai-llm",
                provider_model="gpt-5.6-sol",
                protocol="chat",
                enabled=True,
                priority=10,
                concurrency=2,
                verification="passed",
                capabilities={},
                pricing={},
            )
        )
    original = httpx.AsyncClient.send
    calls = []

    async def send(self, req, **kwargs):
        if req.url.host == "ai-aigc.yseeai.com":
            calls.append(req)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "OK"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}, request=req
            )
        return await original(self, req, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    body = {"model": "gpt-5.6-sol", "messages": [{"role": "user", "content": "Test"}]}
    assert (await api.post("/v1/chat/completions", json=body)).status_code == 200
    async with Session.begin() as db:
        route = await db.get(ModelRoute, "test-route")
        route.provider_model = "different-upstream-name"
    assert (await api.post("/v1/chat/completions", json=body)).status_code == 200
    assert len(calls) == 1
    async with Session() as db:
        row = await db.scalar(select(Job).where(Job.model_id == "gpt-5.6-sol"))
        assert row.routing_snapshot["provider_model"] == "gpt-5.6-sol"
    client = (await ctl.post("/admin/clients", json={"name": "business", "billing_enabled": False})).json()
    r = await api.post(
        "/v1/chat/completions",
        json=body,
        headers={"Authorization": "Bearer " + client["api_key"], "X-Test-Supplier": "yseeai", "Idempotency-Key": "other"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_available_route_does_not_require_original_channel_credentials(service, monkeypatch):
    from gateway.db import Model, ModelRoute, Session

    api, _, _, _ = service
    # 原目录渠道没有凭据，但用户配置的替代路由完整可用。
    monkeypatch.delenv("YINGHE_LLM_API_KEY", raising=False)
    async with Session.begin() as db:
        model = await db.get(Model, "gpt-5.6-sol")
        model.capabilities = {"unified_catalog": True}
        db.add(
            ModelRoute(
                id="available-overseas",
                model_id=model.id,
                supplier="yseeai",
                channel="yseeai-llm",
                provider_model="gpt-5.6-sol",
                protocol="chat",
                enabled=True,
                priority=10,
                concurrency=2,
                verification="passed",
                capabilities={},
                pricing={},
            )
        )
    original = httpx.AsyncClient.send
    seen = []

    async def send(self, request, **kwargs):
        if request.url.host == "ai-aigc.yseeai.com":
            seen.append(request.url.host)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "OK"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
                request=request,
            )
        return await original(self, request, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    response = await api.post("/v1/chat/completions", json={"model": "gpt-5.6-sol", "messages": [{"role": "user", "content": "test"}]})
    assert response.status_code == 200, response.text
    assert seen == ["ai-aigc.yseeai.com"]


@pytest.mark.asyncio
async def test_verification_requires_matching_attributed_success(service):
    from gateway.db import Job, ModelRoute, Session

    api, ctl, _, c = service
    async with Session.begin() as db:
        route = ModelRoute(
            id="verify-route",
            model_id="gpt-5.6-sol",
            supplier="yseeai",
            channel="yseeai-llm",
            provider_model="gpt-5.6-sol",
            protocol="chat",
            enabled=False,
            priority=1,
            concurrency=1,
            verification="pending",
            capabilities={},
            pricing={},
        )
        db.add(route)
    body = {
        "job_id": "fixture-acceptance",
        "review_note": "Synthetic review; no generation",
        "parameters_checked": True,
        "result_checked": True,
        "usage_checked": True,
    }
    assert (await ctl.post("/admin/routes/verify-route/verify", json=body)).status_code == 409
    async with Session.begin() as db:
        db.add(
            Job(
                id=body["job_id"],
                client_id=c["id"],
                user_id="u1",
                model_id="gpt-5.6-sol",
                kind="chat",
                route_id=route.id,
                channel=route.channel,
                protocol=route.protocol,
                routing_snapshot={"channel": route.channel, "provider_model": route.provider_model, "protocol": route.protocol},
                status="succeeded",
                payload={"messages": []},
                request_hash="fixture",
                idempotency_key="fixture-verification",
                origin="agent_test",
                agent_name="code-agent",
                agent_run_id="fixture-run",
                test_run_id="fixture-run",
                usage={"completion_tokens": 1},
            )
        )
    assert (await ctl.post("/admin/routes/verify-route/verify", json={**body, "usage_checked": False})).status_code == 422
    response = await ctl.post("/admin/routes/verify-route/verify", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["verification"] == "passed" and response.json()["enabled"] is False
    async with Session.begin() as db:
        r = await db.get(ModelRoute, route.id)
        r.provider_model = "changed-after-test"
    assert (await ctl.post("/admin/routes/verify-route/verify", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_admin_can_edit_route_concurrency_to_150(service):
    from gateway.db import Model, ModelRoute, Session

    _, ctl, _, _ = service
    async with Session.begin() as db:
        model = await db.get(Model, "gpt-5.6-sol")
        model.enabled = True
        db.add(
            ModelRoute(
                id="manual-limit",
                model_id="gpt-5.6-sol",
                supplier="yseeai",
                channel="yseeai-llm",
                provider_model="gpt-5.6-sol",
                protocol="chat",
                enabled=False,
                priority=10,
                concurrency=2,
                verification="pending",
                capabilities={},
                pricing={},
            )
        )
    response = await ctl.patch("/admin/routes/manual-limit", json={"concurrency": 150, "enabled": False})
    assert response.status_code == 200, response.text
    async with Session() as db:
        route = await db.get(ModelRoute, "manual-limit")
        assert route.concurrency == 150
        assert not route.enabled
        assert (await db.get(Model, "gpt-5.6-sol")).enabled
    assert (await ctl.patch("/admin/routes/manual-limit", json={"concurrency": 1000})).status_code == 200
    for invalid in (0, 1001):
        assert (await ctl.patch("/admin/routes/manual-limit", json={"concurrency": invalid})).status_code == 422
