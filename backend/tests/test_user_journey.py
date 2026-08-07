from __future__ import annotations

import time
import io
import zipfile


ASS_CONTENT = b"""[Script Info]
Script Type: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,20
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,First line
Dialogue: 0,0:00:04.20,0:00:07.00,Default,,0,0,0,,Second line
"""


def wait_for_job(client, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/api/generations/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def test_complete_api_user_journey(client, monkeypatch, tmp_path) -> None:
    from app import main
    from app import domain
    class MemoryStorage:
        objects = {}
        async def put_bytes(self, key, content, content_type=None):
            self.objects[key] = content
            return f"https://tos.test/{key}"
    storage = MemoryStorage()
    monkeypatch.setattr(main, "get_storage", lambda: storage)
    monkeypatch.setattr(domain, "get_storage", lambda: storage)

    async def fake_storyboard_line(**kwargs):
        assert kwargs["current"]["lyrics"] == "First line Second line"
        assert len(kwargs["full_context"]["allLyrics"]) == 1
        assert "图片ID：020" in kwargs["allowed_humans"][0]["systemPrompt"]
        return {"scenePrompt": "sunlit room", "shotPrompt": "slow push in", "digitalHumanIds": ["dh-system-020"], "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}, "requestId": "req-test"}

    async def fake_image(payload, job):
        assert payload.prompt == "sunlit room"
        await main.jobs.update_progress(job, 50)
        return {"urls": ["https://tos.test/images/scene.png"]}

    async def fake_video(payload, job):
        assert payload.image_urls == ["https://tos.test/images/scene.png"]
        assert payload.ratio == "16:9"
        await main.jobs.update_progress(job, 60)
        return {
            "videoUrl": "https://tos.test/videos/shot.mp4",
            "coverUrl": "https://tos.test/images/scene.png",
            "duration": payload.duration,
        }

    monkeypatch.setattr(domain, "generate_storyboard_line", fake_storyboard_line)
    monkeypatch.setattr(main, "generate_image", fake_image)
    monkeypatch.setattr(main, "generate_video", fake_video)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    project = client.post("/api/projects", json={"name": "Journey project"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    upload = client.post(
        "/api/uploads?category=references",
        files={"file": ("reference.png", b"png-data", "image/png")},
    )
    assert upload.status_code == 200
    assert upload.json()["url"].startswith("https://tos.test/users/")

    storyboard = client.post(
        "/api/storyboards/ass",
        data={
            "project_id": project_id,
            "song_id": "10012204",
            "digital_human_ids": '["dh-system-020"]',
            "extra_requirement": "cinematic",
        },
        files={"ass_file": ("10012204-journey.ass", ASS_CONTENT, "text/plain")},
    )
    assert storyboard.status_code == 200
    line = storyboard.json()["lines"][0]
    assert line["generationStatus"] == "pending"
    assert line["plannedDuration"] > 0
    generated_line = client.post(f"/api/tasks/{storyboard.json()['taskId']}/storyboard-lines/{line['id']}/generate", json={})
    assert generated_line.status_code == 200, generated_line.text
    assert generated_line.json()["usage"] == {"inputTokens": 120, "outputTokens": 40, "cachedInputTokens": 0, "totalTokens": 160}
    line = generated_line.json()

    image_created = client.post("/api/generations/images", json={"prompt": line["scenePrompt"], "project_task_id": storyboard.json()["taskId"], "storyboard_line_id": line["id"], "purpose": "scene"})
    assert image_created.status_code == 202
    image_job = wait_for_job(client, image_created.json()["id"])
    assert image_job["status"] == "succeeded"
    scene_url = image_job["result"]["urls"][0]

    video_created = client.post(
        "/api/generations/videos",
        json={
            "prompt": f'{line["scenePrompt"]}. {line["shotPrompt"]}',
            "duration": 5,
            "ratio": "16:9",
            "image_urls": [scene_url],
            "project_task_id": storyboard.json()["taskId"],
            "storyboard_line_id": line["id"],
        },
    )
    assert video_created.status_code == 202
    video_job = wait_for_job(client, video_created.json()["id"])
    assert video_job["status"] == "succeeded"
    assert video_job["result"]["videoUrl"] == "https://tos.test/videos/shot.mp4"
    usage = client.get(f"/api/token-usage?project_task_id={storyboard.json()['taskId']}").json()
    assert usage["summary"]["inputTokens"] == 120
    assert usage["summary"]["outputTokens"] == 40
    assert {item["operation"] for item in usage["records"]} == {"storyboard_line", "generation_image", "generation_video"}

    class FakeResponse:
        content = b"video-bytes"
        def raise_for_status(self): pass
    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url): return FakeResponse()
    monkeypatch.setattr(domain.httpx, "AsyncClient", FakeClient)
    exported = client.post(f"/api/tasks/{storyboard.json()['taskId']}/material-export")
    assert exported.status_code == 201, exported.text
    archive = next(value for key, value in storage.objects.items() if key.endswith(".zip"))
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert "prompts.md" in bundle.namelist()
        assert any(name.startswith("videos/") for name in bundle.namelist())
        assert "sunlit room" in bundle.read("prompts.md").decode()

    chat = client.post("/api/chat/sessions", json={})
    assert chat.status_code == 201
    session_id = chat.json()["id"]
    assert client.get(f"/api/chat/{session_id}").status_code == 200
    assert client.delete(f"/api/chat/{session_id}").json() == {"ok": True}


def test_user_journey_rejects_invalid_inputs(client) -> None:
    project_id = client.post("/api/projects", json={"name": "Invalid input project"}).json()["id"]
    bad_ass = client.post(
        "/api/storyboards/ass",
        data={"project_id": project_id, "song_id": "10012204", "digital_human_ids": "not-json"},
        files={"ass_file": ("10012204-journey.ass", ASS_CONTENT, "text/plain")},
    )
    assert bad_ass.status_code == 422

    unknown_song = client.post(
        "/api/storyboards/ass",
        data={"project_id": project_id, "song_id": "99999999", "digital_human_ids": "[]"},
        files={"ass_file": ("99999999-unknown.ass", ASS_CONTENT, "text/plain")},
    )
    assert unknown_song.status_code == 422
    assert "未匹配到歌曲情感标注数据" in unknown_song.json()["detail"]

    mismatched_song = client.post(
        "/api/storyboards/ass",
        data={"project_id": project_id, "song_id": "16011771", "digital_human_ids": "[]"},
        files={"ass_file": ("10012204-mismatch.ass", ASS_CONTENT, "text/plain")},
    )
    assert mismatched_song.status_code == 422
    assert "不一致" in mismatched_song.json()["detail"]

    bad_video = client.post(
        "/api/generations/videos",
        json={"prompt": "test", "duration": 1, "ratio": "21:9"},
    )
    assert bad_video.status_code == 422


def test_ass_storyboard_generates_one_line_with_full_lyrics_context(client, monkeypatch) -> None:
    from app import domain, main

    class MemoryStorage:
        async def put_bytes(self, key, content, content_type=None):
            return f"https://tos.test/{key}"

    monkeypatch.setattr(main, "get_storage", lambda: MemoryStorage())
    received = []

    async def fake_line(**kwargs):
        received.append(kwargs)
        return {"scenePrompt": f"scene-{kwargs['current']['index']}", "shotPrompt": "shot", "digitalHumanIds": [], "usage": {"input_tokens": 10, "output_tokens": 5}}

    monkeypatch.setattr(domain, "generate_storyboard_line", fake_line)
    project_id = client.post("/api/projects", json={"name": "Progressive ASS"}).json()["id"]
    content = b"""[Script Info]\nScript Type: v4.00+\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: Default,Arial,20\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,First\nDialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,Second\n"""
    prepared = client.post("/api/storyboards/ass", data={"project_id": project_id, "song_id": "10012204", "digital_human_ids": "[]"}, files={"ass_file": ("10012204-progressive.ass", content, "text/plain")})
    assert prepared.status_code == 200
    body = prepared.json()
    assert [line["generationStatus"] for line in body["lines"]] == ["pending", "pending"]
    for index, line in enumerate(body["lines"]):
        response = client.post(f"/api/tasks/{body['taskId']}/storyboard-lines/{line['id']}/generate", json={})
        assert response.status_code == 200
        if index == 0:
            repeated = client.post(f"/api/tasks/{body['taskId']}/storyboard-lines/{line['id']}/generate", json={})
            assert repeated.status_code == 200
    assert [call["current"]["lyrics"] for call in received] == ["First", "Second"]
    assert received[0]["full_context"]["songEmotion"]["songName"] == "他不爱我"
    assert [[item["lyrics"] for item in call["full_context"]["allLyrics"]] for call in received] == [["First", "Second"], ["First", "Second"]]
    task = client.get(f"/api/tasks/{body['taskId']}").json()
    assert task["status"] == "ready"
