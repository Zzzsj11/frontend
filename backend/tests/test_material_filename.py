import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock
from urllib.parse import unquote

from test_mv_export import export_case as export_case

from app import domain, storage
from app.database import session_factory
from app.material_filename import zip_filename
from app.models import MaterialExportModel, ProjectTaskModel


def test_zip_filename_priority_and_filesystem_limits():
    config = {"genre": "流行歌曲", "secondary_category": "爱情消极", "tertiary_category": "失恋"}
    assert zip_filename(["林夏", "陈默"], config, "标题") == "林夏-陈默.zip"
    assert zip_filename([], config, "标题") == "流行歌曲-爱情消极-失恋.zip"
    assert zip_filename([], {"genre": "戏曲"}, "标题") == "戏曲.zip"
    assert zip_filename([], {}, "子/项目.") == "子_项目.zip"
    assert zip_filename([], {}, "CON") == "_CON.zip"
    assert len(zip_filename(["夏" * 200], {}, "").encode()) <= 255


def test_signed_archive_uses_export_snapshot_and_handles_old_tos_records(client, export_case, monkeypatch):
    headers, task_id = export_case
    response = client.post(f"/api/tasks/{task_id}/material-exports", headers=headers)
    assert response.status_code == 202
    export = response.json()
    assert export["metadata"]["downloadFilename"] == "ASS MV.zip"
    endpoint = f"/api/material-exports/{export['id']}/download"
    assert client.get(endpoint, headers=headers).status_code == 409
    assert client.get(endpoint).status_code == 404  # Another logged-in account.
    monkeypatch.setattr(storage, "settings", replace(storage.settings, tos_public_domain="history.example"))
    signer = AsyncMock(return_value="https://history.example/signed")
    monkeypatch.setattr(domain, "sign_attachment_url", signer)

    async def prepare(legacy):
        async with session_factory() as db:
            row = await db.get(MaterialExportModel, export["id"])
            row.status = "ready"
            row.archive_url = f"https://history.example/users/{row.user_id}/exports/sample.zip"
            task = await db.get(ProjectTaskModel, task_id)
            task.storyboard_config = {"genre": "流行歌曲", "secondary_category": "爱情消极"}
            if legacy:
                row.result_metadata = {}
            await db.commit()

    for legacy, expected in ((False, "ASS MV.zip"), (True, "流行歌曲-爱情消极.zip")):
        asyncio.run(prepare(legacy))
        response = client.get(endpoint, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["url"] == signer.return_value
        assert unquote(signer.await_args.args[1]).endswith("filename*=UTF-8''" + expected)


def test_cast_filename_follows_roster_then_exported_shot_order(client, export_case):
    headers, task_id = export_case
    humans = [item for item in client.get("/api/digital-humans", headers=headers).json() if item["scope"] == "system"][:4]
    a, b, c, d = humans
    response = client.put(f"/api/tasks/{task_id}/cast", headers=headers, json={"digital_human_ids": [b["id"], a["id"]]})
    assert response.status_code == 200
    for line, cast in ((1, [c, d]), (0, [a, d])):
        response = client.patch(f"/api/storyboard-lines/{task_id}-l{line}", headers=headers, json={"digital_human_ids": [human["id"] for human in cast]})
        assert response.status_code == 200
    response = client.post(f"/api/tasks/{task_id}/material-exports", headers=headers)
    assert response.status_code == 202
    assert response.json()["metadata"]["downloadFilename"] == "-".join(human["name"] for human in (b, a, d, c)) + ".zip"
