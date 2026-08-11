from __future__ import annotations

import io
import time
import zipfile

from PIL import Image

from app.media_constraints import normalize_video_duration

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


def outline_result(segments, role_ids):
    return {
        "globalVisual": {
            "visualStyle": "电影写实",
            "colorPalette": "冷蓝与暖橙",
            "lighting": "统一夜景光线",
            "weather": "细雨",
            "timeOfDay": "夜晚",
            "continuityRules": ["服装不变", "地点移动可解释"],
        },
        "locations": [{"id": "street", "name": "街道", "purpose": "推进关系"}],
        "motifs": [{"id": "rain", "name": "雨", "meaning": "压抑", "maxAppearances": len(segments)}],
        "shots": [
            {
                "index": index,
                "shotType": "character" if role_ids else "empty",
                "intent": f"歌词意图 {index}",
                "requiredCharacterIds": list(role_ids),
                "locationId": "street",
                "locationChange": index == 0,
                "characterAction": "人物回应歌词" if role_ids else "无人环境变化",
                "emotionalFocus": "克制",
                "cameraPurpose": "推进叙事",
                "motifIds": ["rain"],
                "gapAfterAllocation": "current"
                if index + 1 < len(segments) and 0 < float(segments[index + 1].get("start") or 0) - float(_segment.get("end") or 0) <= 2
                else "none",
                "sceneIndex": 0,
                "outlineStatus": "ready",
            }
            for index, _segment in enumerate(segments)
        ],
        "scenePlan": [],
        "failedSegments": [],
        "usage": {},
        "usageRecords": [{"operation": "ass_story_outline", "usage": {}, "requestId": "outline-test"}],
        "requestId": "outline-test",
    }


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
    from app import domain, main

    class MemoryStorage:
        objects = {}

        async def put_bytes(self, key, content, content_type=None):
            self.objects[key] = content
            return f"https://tos.test/{key}"

        async def put_file(self, key, path, content_type=None):
            self.objects[key] = path.read_bytes()
            return f"https://tos.test/{key}"

    storage = MemoryStorage()
    monkeypatch.setattr(main, "get_storage", lambda: storage)
    monkeypatch.setattr(domain, "get_storage", lambda: storage)

    async def fake_storyboard_line(**kwargs):
        assert kwargs["current"]["lyrics"] == "First line"
        assert len(kwargs["full_context"]["allLyrics"]) == 3
        assert "图片ID：020" in kwargs["allowed_humans"][0]["systemPrompt"]
        return {
            "scenePrompt": "sunlit room",
            "shotPrompt": "slow push in",
            "digitalHumanIds": ["dh-system-020"],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
            "requestId": "req-test",
        }

    async def fake_outline(**kwargs):
        return outline_result(kwargs["segments"], ["dh-system-020"])

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
    monkeypatch.setattr(domain, "generate_ass_story_outline", fake_outline)
    monkeypatch.setattr(main, "generate_image", fake_image)
    monkeypatch.setattr(main, "generate_video", fake_video)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    project = client.post("/api/projects", json={"name": "Journey project"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    image = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    upload = client.post(
        "/api/uploads?category=references",
        files={"file": ("reference.png", image.getvalue(), "image/png")},
    )
    assert upload.status_code == 200
    assert upload.json()["url"].startswith("https://tos.test/users/")
    assert upload.json()["thumbnailUrl"].startswith("https://tos.test/users/")

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
    assert storyboard.json()["title"] == "10012204"
    assert storyboard.json()["status"] == "parsed"
    line = storyboard.json()["lines"][0]
    assert line["generationStatus"] == "pending"
    assert line["plannedDuration"] > 0
    assert line["shotOptions"]["duration"] == normalize_video_duration(line["plannedDuration"])
    assert line["shotOptions"]["gapAfterAllocation"] in {"current", "next", "none"}
    assert line["shotOptions"]["outlineStatus"] == "pending"
    blocked_line = client.post(f"/api/tasks/{storyboard.json()['taskId']}/storyboard-lines/{line['id']}/generate", json={})
    assert blocked_line.status_code == 422
    outline = client.post(f"/api/tasks/{storyboard.json()['taskId']}/storyboard-outline/regenerate")
    assert outline.status_code == 200, outline.text
    assert outline.json()["failedSegments"] == []
    generated_line = client.post(f"/api/tasks/{storyboard.json()['taskId']}/storyboard-lines/{line['id']}/generate", json={})
    assert generated_line.status_code == 200, generated_line.text
    assert generated_line.json()["usage"] == {"inputTokens": 120, "outputTokens": 40, "cachedInputTokens": 0, "totalTokens": 160}
    line = generated_line.json()
    assert line["shotOptions"]["ratio"] == "16:9"
    assert line["shotOptions"]["resolution"] == "720p"
    assert line["shotOptions"]["imageModel"] == "gpt-image-2"
    assert line["shotOptions"]["videoModel"] == "doubao-seedance-2.0"

    image_created = client.post(
        "/api/generations/images", json={"prompt": line["scenePrompt"], "project_task_id": storyboard.json()["taskId"], "storyboard_line_id": line["id"], "purpose": "scene"}
    )
    assert image_created.status_code == 202
    image_job = wait_for_job(client, image_created.json()["id"])
    assert image_job["status"] == "succeeded"
    scene_url = image_job["result"]["urls"][0]

    video_created = client.post(
        "/api/generations/videos",
        json={
            "prompt": f"{line['scenePrompt']}. {line['shotPrompt']}",
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
    assert {item["operation"] for item in usage["records"]} == {"ass_story_outline", "storyboard_line", "generation_image", "generation_video"}

    async def fake_download_to_path(url, destination, max_bytes=500 * 1024 * 1024, progress_callback=None):
        destination.write_bytes(b"video-bytes")
        if progress_callback:
            await progress_callback(len(b"video-bytes"), len(b"video-bytes"))
        return url, "video/mp4", len(b"video-bytes")

    monkeypatch.setattr(domain, "download_public_url_to_path", fake_download_to_path)
    exported = client.post(f"/api/tasks/{storyboard.json()['taskId']}/material-exports")
    assert exported.status_code == 202, exported.text
    export_job = wait_for_job(client, exported.json()["jobId"])
    assert export_job["status"] == "succeeded", export_job["error"]
    export_status = client.get(f"/api/material-exports/{exported.json()['id']}").json()
    assert export_status["progress"] == 100
    assert export_status["stage"] == "导出完成"
    assert export_status["totalAssets"] == 2
    assert client.get(f"/api/tasks/{storyboard.json()['taskId']}/material-exports").json()[0]["id"] == exported.json()["id"]
    archive = next(value for key, value in storage.objects.items() if key.endswith(".zip"))
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert "prompts.md" in bundle.namelist()
        assert any(name.startswith("videos/") for name in bundle.namelist())
        assert any(name.startswith("characters/") for name in bundle.namelist())
        assert "sunlit room" in bundle.read("prompts.md").decode()
        assert "人物素材" in bundle.read("prompts.md").decode()

    regenerated_outline = client.post(f"/api/tasks/{storyboard.json()['taskId']}/storyboard-outline/regenerate")
    assert regenerated_outline.status_code == 200, regenerated_outline.text
    assert regenerated_outline.json()["storyBible"]["shots"][0]["shotType"] == "character"
    replanned = client.get(f"/api/tasks/{storyboard.json()['taskId']}").json()["lines"][0]
    assert replanned["generationStatus"] == "pending"
    assert replanned["scenePrompt"] == ""
    assert replanned["digitalHumanIds"] == ["dh-system-020"]

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

    unsupported_video_model = client.post(
        "/api/generations/videos",
        json={"prompt": "test", "duration": 5, "ratio": "16:9", "model": "future-video-model"},
    )
    assert unsupported_video_model.status_code == 422

    unsupported_image_model = client.post(
        "/api/generations/images",
        json={"prompt": "test", "model": "future-image-model"},
    )
    assert unsupported_image_model.status_code == 422


def test_ass_storyboard_generates_each_lyric_and_long_gap_with_full_context(client, monkeypatch) -> None:
    from app import domain, main

    class MemoryStorage:
        async def put_bytes(self, key, content, content_type=None):
            return f"https://tos.test/{key}"

    monkeypatch.setattr(main, "get_storage", lambda: MemoryStorage())
    received = []

    async def fake_line(**kwargs):
        received.append(kwargs)
        return {"scenePrompt": f"scene-{kwargs['current']['index']}", "shotPrompt": "shot", "digitalHumanIds": [], "usage": {"input_tokens": 10, "output_tokens": 5}}

    async def fake_outline(**kwargs):
        return outline_result(kwargs["segments"], [])

    monkeypatch.setattr(domain, "generate_storyboard_line", fake_line)
    monkeypatch.setattr(domain, "generate_ass_story_outline", fake_outline)
    project_id = client.post("/api/projects", json={"name": "Progressive ASS"}).json()["id"]
    content = b"""[Script Info]\nScript Type: v4.00+\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: Default,Arial,20\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,First\nDialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,Second\n"""
    prepared = client.post(
        "/api/storyboards/ass",
        data={"project_id": project_id, "song_id": "10012204", "digital_human_ids": "[]"},
        files={"ass_file": ("10012204-progressive.ass", content, "text/plain")},
    )
    assert prepared.status_code == 200
    body = prepared.json()
    assert body["status"] == "parsed"
    assert [line["generationStatus"] for line in body["lines"]] == ["pending", "pending", "pending", "pending"]
    assert [line["shotOptions"]["segmentType"] for line in body["lines"]] == ["lyric", "interlude", "lyric", "outro"]
    regenerated = client.post(f"/api/tasks/{body['taskId']}/storyboard-outline/regenerate")
    assert regenerated.status_code == 200, regenerated.text
    for index, line in enumerate(body["lines"]):
        response = client.post(f"/api/tasks/{body['taskId']}/storyboard-lines/{line['id']}/generate", json={})
        assert response.status_code == 200
        if index == 0:
            repeated = client.post(f"/api/tasks/{body['taskId']}/storyboard-lines/{line['id']}/generate", json={})
            assert repeated.status_code == 200
    assert [call["current"]["lyrics"] for call in received] == ["First", "", "Second", ""]
    assert received[0]["full_context"]["songEmotion"]["songName"] == "他不爱我"
    assert [[item["lyrics"] for item in call["full_context"]["allLyrics"]] for call in received] == [["First", "", "Second", ""]] * 4
    task = client.get(f"/api/tasks/{body['taskId']}").json()
    assert task["status"] == "ready"
