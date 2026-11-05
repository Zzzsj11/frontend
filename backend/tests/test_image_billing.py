import asyncio
from unittest.mock import AsyncMock

from sqlalchemy import select

from app import image_billing
from app.database import session_factory
from app.models import GenerationJobModel, UserModel


def test_pending_then_settled_image_is_charged_once_to_original_owner(client, monkeypatch):
    jid = "image-bill-only"
    tid = "platform-original"

    async def seed():
        async with session_factory() as db:
            owner = await db.scalar(select(UserModel).where(UserModel.username == "admin"))
            db.add(
                GenerationJobModel(
                    id=jid,
                    kind="image",
                    status="succeeded",
                    user_id=owner.id,
                    provider="all-in-one",
                    provider_task_id=tid,
                    generation_origin="agent_test",
                    agent_name="code-agent",
                    agent_run_id="bill-test",
                    request={"_provider": "all-in-one", "model": "gpt-image-2-all-in-one"},
                    result={"urls": ["existing"], "usage": {"input_images": 15}},
                )
            )
            await db.commit()

    asyncio.run(seed())
    bill = {"status": "settled", "points": "10.500000"}
    pending = {"id": tid, "billing": {"status": "pending", "points": None}}
    final = {"id": tid, "billing": bill}
    monkeypatch.setattr(image_billing, "query_task", AsyncMock(side_effect=[pending, final, final]))
    for expected in ["pending", "billing_refreshed", "billing_refreshed"]:
        response = client.post(f"/api/admin/jobs/{jid}/sync")
        assert response.json().get("action") == expected, response.text
    records = client.get("/api/admin/image-billing?username=admin&origin=agent_test").json()
    matches = [row for row in records if row["jobId"] == jid]
    assert len(matches) == 1 and matches[0]["points"] == "10.500000" and matches[0]["agentRunId"] == "bill-test"
    assert client.get("/api/admin/image-billing?username=someone-else").json() == []
    result = client.get("/api/generations/" + jid).json()["result"]
    assert result == {"urls": ["existing"], "usage": {"input_images": 15, "platformBilling": bill}}
