"""Private history filtering and details; isolated database, no provider calls."""

import pytest
from test_portal_billing import user_key


@pytest.mark.asyncio
async def test_history_filters_pagination_and_private_job_details(service):
    from gateway.db import Job, Ledger, Session

    api, ctl, _, _ = service
    uid, token, key = await user_key(api, ctl)
    other_uid, other_token, other = await user_key(api, ctl, "other")
    auth = {"Authorization": "Bearer " + token}
    other_auth = {"Authorization": "Bearer " + other_token}
    second = (await api.post("/portal/keys", headers=auth, json={"name": "Second", "monthly_points": 50})).json()
    async with Session.begin() as db:
        for owner, cid, prefix in [(uid, key["id"], "mine"), (other_uid, other["id"], "other")]:
            db.add(
                Job(
                    id=prefix,
                    client_id=cid,
                    user_id=owner,
                    model_id="gpt-5.6-sol",
                    kind="chat",
                    channel="yinghe-llm",
                    protocol="chat",
                    payload={},
                    request_hash=prefix,
                    idempotency_key=prefix,
                    status="succeeded",
                    usage={},
                    charged_points=3,
                    reserved_points=0,
                    billing_status="settled",
                )
            )
            for n in range(12):
                db.add(
                    Ledger(
                        id=f"{prefix}-{n}",
                        client_id=cid,
                        user_id=owner,
                        job_id=prefix,
                        operation_id=f"{prefix}-{n}",
                        kind="task_charge",
                        points=-3,
                        monthly_after=20 - n,
                        extra_after=0,
                        actor="test",
                        reason="synthetic",
                        evidence={},
                    )
                )
    result = (await api.get(f"/portal/ledger?client_id={key['id']}&kind=task_charge&limit=10&page=2", headers=auth)).json()
    assert result["total"] == 12 and result["page"] == 2 and len(result["items"]) == 2
    assert all(row["client_id"] == key["id"] and row["key_name"] for row in result["items"])
    assert (await api.get("/portal/ledger?kind=task_charge&limit=10&page=999", headers=auth)).json()["page"] == 2
    assert (await api.get(f"/portal/ledger?client_id={second['id']}&kind=task_charge", headers=auth)).json()["total"] == 0
    assert (await api.get(f"/portal/ledger?client_id={other['id']}", headers=auth)).json()["total"] == 0
    assert (await api.get("/portal/jobs/mine", headers=other_auth)).status_code == 404
    detail = await api.get("/portal/jobs/mine", headers=auth)
    assert detail.status_code == 200 and detail.json()["billing"]["points"] == "3.000000"
    assert (await api.get(f"/portal/jobs?client_id={other['id']}", headers=auth)).json()["total"] == 0
    assert (await api.delete(f"/portal/keys/{key['id']}", headers=auth)).status_code == 204
    keys = (await api.get("/portal/history-keys", headers=auth)).json()
    assert any(k["id"] == key["id"] and k["deleted"] for k in keys)
    assert not any(k["id"] == other["id"] for k in keys)
    assert (await api.get("/portal/jobs/mine", headers=auth)).status_code == 200
    assert (await api.get(f"/portal/ledger?client_id={key['id']}&kind=task_charge", headers=auth)).json()["total"] == 12
    assert (await api.get("/portal/history-keys")).status_code == 401
