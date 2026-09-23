from __future__ import annotations

import importlib.util
import io
import json
import socket
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("These script tests must never use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def generator():
    return _load_script("generate-neutral-identity-manifest")


def _human_api(code="001", **overrides):
    return {
        "id": f"dh-system-{code}",
        "assetCode": code,
        "name": "DO-NOT-USE-NAME",
        "scope": "system",
        "readOnly": True,
        "originalAvatar": f"https://media.invalid/{code}.jpg",
        "avatar": f"https://media.invalid/{code}-thumb.jpg",
        "ageDescription": "",
        "gender": "",
        **overrides,
    }


def _generation_api(monkeypatch, module, humans, failed_sources=()):
    requests = []
    jobs = {}

    def respond(request):
        requests.append(request)
        if request.method == "GET" and request.url.path == "/api/digital-humans":
            return httpx.Response(200, json=humans)
        if request.method == "POST" and request.url.path == "/api/generations/images":
            payload = json.loads(request.content)
            if payload["images"][0] in failed_sources:
                return httpx.Response(500, json={"error": "mock failure"})
            job_id = f"job-{len(jobs) + 1}"
            jobs[job_id] = {"id": job_id, "status": "succeeded", "result": {"urls": [f"https://media.invalid/{job_id}.png"]}}
            return httpx.Response(202, json={"id": job_id})
        if request.method == "GET" and request.url.path.startswith("/api/generations/"):
            return httpx.Response(200, json=jobs[request.url.path.rsplit("/", 1)[-1]])
        raise AssertionError(f"Unexpected API call: {request.method} {request.url}")

    client = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    return requests


def _generator_args(monkeypatch, output, *extra):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate-neutral-identity-manifest.py",
            "--api-base",
            "https://app.invalid",
            "--token",
            "mock-token",
            "--run-id",
            "headshot-test-2026.09_22",
            "--output",
            str(output),
            *extra,
        ],
    )


def test_generation_single_reference_system_only_headers_and_resume(generator, monkeypatch, tmp_path):
    adult = _human_api()
    child = _human_api("031", originalAvatar="", ageDescription="约5岁，学龄前儿童", gender="男")
    private = _human_api("private", scope="private", readOnly=False)
    requests = _generation_api(monkeypatch, generator, [adult, private, child])
    output = tmp_path / "manifest.json"
    _generator_args(monkeypatch, output)
    generator.main()

    payloads = [json.loads(request.content) for request in requests if request.method == "POST"]
    assert len(payloads) == 2
    assert {payload["images"][0] for payload in payloads} == {adult["originalAvatar"], child["avatar"]}
    for payload in payloads:
        assert payload["size"] == "1024x1536"
        assert payload["n"] == 1
        assert payload["model"] == "gpt-image-2.5-sunburst"
        assert payload["purpose"] == "digital_human"
        assert len(payload["images"]) == 1
        assert payload["portrait"]["style"] == ""
        description = payload["portrait"]["description"]
        assert "DO-NOT-USE-NAME" not in description
        assert "头肩大头照" in description and "纯白无图案T恤" in description and "纯灰背景" in description
        assert "卡通人物保持卡通风格" in description and "不得成人化" in description
        if payload["images"] == [child["avatar"]]:
            assert child["ageDescription"] in description and "男" in description
    assert all("uploads" not in request.url.path for request in requests)
    for request in requests:
        assert request.headers["Authorization"] == "Bearer mock-token"
        assert request.headers["X-Agent-Name"] == "code-agent"
        assert request.headers["X-Agent-Run-Id"] == "headshot-test-2026.09_22"
        assert request.headers["X-Test-Run-Id"] == "headshot-test-2026.09_22"

    before = output.read_bytes()
    generator.main()
    assert output.read_bytes() == before
    assert len([request for request in requests if request.method == "POST"]) == 2
    assert {row["code"] for row in json.loads(before)} == {"001", "031"}


@pytest.mark.parametrize("wanted", ["dh-system-private", "unknown", " "])
def test_ids_cannot_bypass_system_filter(generator, monkeypatch, tmp_path, wanted):
    requests = _generation_api(monkeypatch, generator, [_human_api(), _human_api("private", scope="private", readOnly=False)])
    _generator_args(monkeypatch, tmp_path / "output.json", "--ids", "dh-system-001", wanted)
    with pytest.raises(SystemExit):
        generator.main()
    assert not any(request.method == "POST" for request in requests)


def test_ids_and_limit_only_select_requested_systems(generator, monkeypatch, tmp_path):
    requests = _generation_api(monkeypatch, generator, [_human_api(), _human_api("002"), _human_api("003")])
    _generator_args(monkeypatch, tmp_path / "output.json", "--ids", "dh-system-002", "dh-system-003", "--limit", "1")
    generator.main()
    assert [json.loads(request.content)["images"] for request in requests if request.method == "POST"] == [["https://media.invalid/002.jpg"]]


@pytest.mark.parametrize(
    "extra",
    [
        ("--run-id", ""),
        ("--run-id", " "),
        ("--run-id", "bad\r\nid"),
        ("--run-id", "中文"),
        ("--run-id", "a" * 161),
        ("--token", ""),
        ("--limit", "-1"),
        ("--concurrency", "0"),
        ("--ids",),
        ("--template", "old.png"),
        ("--api-base", "file:///tmp/api"),
        ("--api-base", "https://app.invalid:bad"),
    ],
)
def test_generator_rejects_bad_cli_before_network(generator, monkeypatch, tmp_path, extra):
    client = Mock(side_effect=AssertionError("invalid input must fail before opening a client"))
    monkeypatch.setattr(generator.httpx, "Client", client)
    _generator_args(monkeypatch, tmp_path / "output.json", *extra)
    with pytest.raises(SystemExit):
        generator.main()
    client.assert_not_called()


def test_run_id_max_length_is_preserved(generator):
    headers = generator._headers("token", "a" * 160)
    assert headers["X-Agent-Run-Id"] == headers["X-Test-Run-Id"] == "a" * 160


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{}",
        '[{"id": "a"}]',
        '[{"id": 12, "url": "https://media.invalid/a"}]',
        '[{"id": "a", "scope": "private", "url": "https://media.invalid/a"}]',
        '[{"id": "a", "url": "https://media.invalid/a"}, {"id": "a", "url": "https://media.invalid/b"}]',
    ],
)
def test_corrupt_resume_output_fails_closed(generator, monkeypatch, tmp_path, content):
    output = tmp_path / "output.json"
    output.write_text(content)
    client = Mock(side_effect=AssertionError("corrupt output must fail offline"))
    monkeypatch.setattr(generator.httpx, "Client", client)
    _generator_args(monkeypatch, output)
    with pytest.raises(SystemExit):
        generator.main()
    client.assert_not_called()
    assert output.read_text() == content


def test_missing_output_parent_fails_before_network(generator, monkeypatch, tmp_path):
    client = Mock(side_effect=AssertionError("missing parent must fail offline"))
    monkeypatch.setattr(generator.httpx, "Client", client)
    _generator_args(monkeypatch, tmp_path / "missing" / "output.json")
    with pytest.raises(SystemExit):
        generator.main()
    client.assert_not_called()


def test_all_references_validated_before_generation(generator, monkeypatch, tmp_path):
    requests = _generation_api(monkeypatch, generator, [_human_api(), _human_api("002", originalAvatar=None, avatar=None)])
    _generator_args(monkeypatch, tmp_path / "output.json")
    with pytest.raises(ValueError, match="URL"):
        generator.main()
    assert not any(request.method == "POST" for request in requests)


def test_failed_future_does_not_discard_other_completed_results(generator, monkeypatch, tmp_path):
    humans = [_human_api(), _human_api("002")]
    requests = _generation_api(monkeypatch, generator, humans, failed_sources={humans[0]["originalAvatar"]})
    output = tmp_path / "output.json"
    _generator_args(monkeypatch, output, "--concurrency", "1")
    with pytest.raises(RuntimeError, match="Check existing generation jobs"):
        generator.main()
    rows = {row["id"]: row for row in json.loads(output.read_text())}
    assert set(rows) == {"dh-system-001", "dh-system-002"}
    assert rows["dh-system-001"]["status"] == "submitting"
    assert "generation_job_id" not in rows["dh-system-001"]
    assert rows["dh-system-002"]["status"] == "succeeded"
    request_count = len(requests)
    # A 500 may follow an accepted paid request. Preserve intent and refuse retry offline.
    with pytest.raises(SystemExit):
        generator.main()
    assert len(requests) == request_count
    assert sum(request.method == "POST" and json.loads(request.content)["images"] == [humans[1]["originalAvatar"]] for request in requests) == 1


def test_resume_preserves_existing_rows_when_appending(generator, monkeypatch, tmp_path):
    requests = _generation_api(monkeypatch, generator, [_human_api(), _human_api("002")])
    output = tmp_path / "output.json"
    saved = {"id": "dh-system-001", "scope": "system", "url": "https://media.invalid/saved.png", "generation_job_id": "old-job"}
    output.write_text(json.dumps([saved]))
    _generator_args(monkeypatch, output)
    generator.main()
    rows = json.loads(output.read_text())
    assert rows[0] == saved and rows[1]["id"] == "dh-system-002"
    assert len([request for request in requests if request.method == "POST"]) == 1


@pytest.fixture
def replacer(monkeypatch):
    # Import only inert models. Never load real provider/storage/DB configuration.
    monkeypatch.syspath_prepend(str(ROOT / "backend"))
    database = ModuleType("app.database")
    database.session_factory = Mock(side_effect=AssertionError("DB session must be mocked"))
    providers = ModuleType("app.providers")
    providers.create_real_face_asset = AsyncMock(return_value="asset://mock-yinghe")
    storage = ModuleType("app.storage")
    storage.get_storage = Mock(
        return_value=SimpleNamespace(
            put_bytes=AsyncMock(side_effect=lambda key, content, content_type: f"https://tos.invalid/{key}"),
        )
    )
    monkeypatch.setitem(sys.modules, "app.database", database)
    monkeypatch.setitem(sys.modules, "app.providers", providers)
    monkeypatch.setitem(sys.modules, "app.storage", storage)
    monkeypatch.setattr("dotenv.load_dotenv", Mock())
    return _load_script("replace-digital-human-assets")


def _human_db(module, code="001", **overrides):
    values = dict(
        id=f"dh-system-{code}",
        asset_code=code,
        name="DO-NOT-USE-NAME",
        user_id=None,
        scope="system",
        avatar_url="https://old.invalid/original.jpg",
        avatar_thumbnail_url="https://old.invalid/thumb.jpg",
        asset_avatar_url="asset://old",
        avatar_prompt="old prompt",
        description="old description",
        appearance_style="old appearance",
        clothing_description="old clothing",
        suitable_music_styles="old music",
        system_prompt="old system prompt",
        age_description="约5岁，学龄前儿童",
        gender="男",
    )
    return module.DigitalHumanModel(**{**values, **overrides})


def _session(module, humans):
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: humans)), commit=AsyncMock())
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=session)
    manager.__aexit__ = AsyncMock(return_value=False)
    module.session_factory.side_effect = None
    module.session_factory.return_value = manager
    return session


def _manifest(tmp_path, rows=None):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(rows if rows is not None else [{"id": "dh-system-001", "scope": "system", "url": "https://media.invalid/headshot.png"}]))
    return path


def _image_bytes(size=(1024, 1536)):
    stream = io.BytesIO()
    Image.new("RGB", size, "gray").save(stream, format="PNG")
    return stream.getvalue()


def _download_api(module, monkeypatch, content):
    client = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        return httpx.Response(200, content=content)

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    return requests


def test_jpeg_pair_preserves_portrait_pixels(replacer):
    original, thumbnail = replacer._jpeg_pair(_image_bytes())
    for content, expected in ((original, (1024, 1536)), (thumbnail, (320, 480))):
        with Image.open(io.BytesIO(content)) as image:
            assert image.size == expected
            assert image.format == "JPEG"
            assert image.mode == "RGB"


@pytest.mark.parametrize("size", [(1344, 768), (1600, 900), (512, 768), (1024, 1024)])
def test_jpeg_pair_rejects_wrong_dimensions_without_cropping(replacer, size):
    with pytest.raises(ValueError, match="1024x1536"):
        replacer._jpeg_pair(_image_bytes(size))


def test_jpeg_pair_applies_exif_orientation(replacer):
    stream = io.BytesIO()
    image = Image.new("RGB", (1536, 1024), "gray")
    exif = Image.Exif()
    exif[274] = 6
    image.save(stream, format="JPEG", exif=exif)
    original, thumbnail = replacer._jpeg_pair(stream.getvalue())
    assert Image.open(io.BytesIO(original)).size == (1024, 1536)
    assert Image.open(io.BytesIO(thumbnail)).size == (320, 480)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        {},
        [None],
        [{"id": "", "url": "https://media.invalid/a"}],
        [{"id": 1, "url": "https://media.invalid/a"}],
        [{"id": "a", "url": None}],
        [{"id": "a", "url": "file:///tmp/a"}],
        [{"id": "a", "url": "https://user:pass@media.invalid/a"}],
        [{"id": "a", "url": "https://media.invalid/a\n"}],
        [{"id": "a", "url": "https://media.invalid:bad/a"}],
        [{"id": "a", "scope": "private", "url": "https://media.invalid/a"}],
        [{"id": "a", "url": "https://media.invalid/a"}, {"id": "a", "url": "https://media.invalid/b"}],
    ],
)
async def test_invalid_manifest_rejected_before_db(replacer, tmp_path, rows):
    with pytest.raises(SystemExit):
        await replacer.replace(_manifest(tmp_path, rows), dry_run=False)
    replacer.session_factory.assert_not_called()
    replacer.get_storage.assert_not_called()
    replacer.create_real_face_asset.assert_not_awaited()


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope": "private", "user_id": "dev01"},
        {"scope": "system", "user_id": "dev01"},
        {"asset_code": None},
        {"asset_code": "../bad"},
    ],
)
async def test_db_scope_cannot_be_spoofed_by_manifest(replacer, tmp_path, overrides):
    session = _session(replacer, [_human_db(replacer, **overrides)])
    with pytest.raises(SystemExit):
        await replacer.replace(_manifest(tmp_path), dry_run=False)
    replacer.get_storage.assert_not_called()
    replacer.create_real_face_asset.assert_not_awaited()
    session.commit.assert_not_awaited()
    assert not list(tmp_path.glob("*-backup.json"))


async def test_missing_humans_rejected_before_side_effects(replacer, tmp_path):
    session = _session(replacer, [])
    with pytest.raises(SystemExit, match="missing humans"):
        await replacer.replace(_manifest(tmp_path), dry_run=False)
    session.commit.assert_not_awaited()
    replacer.get_storage.assert_not_called()


async def test_dry_run_backs_up_without_upload_registration_or_db_write(replacer, monkeypatch, tmp_path, capsys):
    human = _human_db(replacer)
    session = _session(replacer, [human])
    client = Mock(side_effect=AssertionError("dry-run must not download or upload"))
    monkeypatch.setattr(replacer.httpx, "AsyncClient", client)
    # Legacy id/url manifests still work, but database scope is authoritative.
    await replacer.replace(_manifest(tmp_path, [{"id": human.id, "url": "https://media.invalid/a"}]), dry_run=True)
    result = json.loads(capsys.readouterr().out)
    backup = json.loads(Path(result["backup"]).read_text())
    assert result["dry_run"] is True
    assert backup[0]["asset_code"] == "001" and backup[0]["avatar_prompt"] == "old prompt"
    assert set(backup[0]) == {column.name for column in replacer.DigitalHumanModel.__table__.columns}
    assert result["requires_alembic"] is True and result["committed"] is False
    assert backup[0]["asset_avatar_url"] == "asset://old"
    assert human.avatar_url == "https://old.invalid/original.jpg"
    assert session.execute.await_count == 1  # No obsolete owner lookup.
    session.commit.assert_not_awaited()
    client.assert_not_called()
    replacer.get_storage.assert_not_called()
    replacer.create_real_face_asset.assert_not_awaited()


async def test_replace_yinghe_only_mapping_backup_and_pixels(replacer, monkeypatch, tmp_path, capsys):
    human = _human_db(replacer)
    session = _session(replacer, [human])
    requests = _download_api(replacer, monkeypatch, _image_bytes())
    await replacer.replace(_manifest(tmp_path), dry_run=False)
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["committed"] is False and result["requires_alembic"] is True
    assert result["status"] == "prepared"
    assert json.loads(Path(result["mapping"]).read_text()) == result
    assert len(requests) == 1
    mapping = result["humans"][0]
    assert mapping["id"] == human.id and mapping["code"] == "001"
    assert mapping["provider"] == "yinghe" and mapping["status"] == "prepared"
    updates = mapping["updates"]
    assert updates["asset_avatar_url"] == "asset://mock-yinghe"
    assert updates["avatar_url"] == "https://tos.invalid/" + mapping["original_key"]
    assert updates["avatar_thumbnail_url"] == "https://tos.invalid/" + mapping["thumbnail_key"]
    calls = replacer.get_storage.return_value.put_bytes.await_args_list
    assert len(calls) == 2
    for call, size in zip(calls, [(1024, 1536), (320, 480)]):
        key, content, content_type = call.args
        assert key.startswith("system/digital-humans/")
        assert content_type == "image/jpeg"
        assert Image.open(io.BytesIO(content)).size == size
    replacer.create_real_face_asset.assert_awaited_once_with(updates["avatar_url"], name=f"mv-001-{result['run_id']}")
    session.commit.assert_not_awaited()
    backup = json.loads(Path(result["backup"]).read_text())[0]
    assert backup["avatar_url"] == "https://old.invalid/original.jpg"
    assert backup["avatar_prompt"] == "old prompt"
    assert mapping["expected_old"] == backup
    assert human.avatar_url == backup["avatar_url"] and human.description == "old description"
    assert human.clothing_description == "old clothing" and human.suitable_music_styles == "old music"
    assert human.name not in updates["description"]
    assert "儿童" in updates["description"] and "卡通" in updates["description"]
    assert updates["clothing_description"] == updates["suitable_music_styles"] == ""


async def test_registration_failure_never_commits_or_changes_humans(replacer, monkeypatch, tmp_path, capsys):
    humans = [_human_db(replacer), _human_db(replacer, "002")]
    session = _session(replacer, humans)
    _download_api(replacer, monkeypatch, _image_bytes())
    replacer.create_real_face_asset.side_effect = ["asset://first", RuntimeError("mock registration failure")]
    path = _manifest(tmp_path, [{"id": human.id, "url": "https://media.invalid/a"} for human in humans])
    with pytest.raises(RuntimeError, match="mock registration failure"):
        await replacer.replace(path, dry_run=False)
    assert all(human.avatar_url == "https://old.invalid/original.jpg" for human in humans)
    session.commit.assert_not_awaited()
    assert len(list(tmp_path.glob("*-backup.json"))) == 1
    # External prepared assets are printed for reconciliation; not rolled back.
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]["updates"]["asset_avatar_url"] == "asset://first"
    result = events[-1]
    assert result["status"] == "reconcile_required" and result["committed"] is False
    assert result["humans"][0]["status"] == "prepared"
    assert result["humans"][1]["status"] == "registering"
    assert json.loads(Path(result["mapping"]).read_text()) == result


@pytest.mark.parametrize("content", [b"not an image", _image_bytes((1344, 768))])
async def test_invalid_download_never_uploads_or_commits(replacer, monkeypatch, tmp_path, content):
    session = _session(replacer, [_human_db(replacer)])
    _download_api(replacer, monkeypatch, content)
    with pytest.raises((ValueError, OSError)):
        await replacer.replace(_manifest(tmp_path), dry_run=False)
    replacer.get_storage.return_value.put_bytes.assert_not_awaited()
    replacer.create_real_face_asset.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_empty_identity_never_falls_back_to_name(replacer):
    human = _human_db(replacer, age_description="", gender=None)
    assert human.name not in replacer._identity_text(human)


@pytest.mark.parametrize("flag", ["--owner-username", "--include-system"])
def test_obsolete_private_migration_cli_removed(replacer, monkeypatch, tmp_path, flag):
    monkeypatch.setattr(sys, "argv", ["replace-digital-human-assets.py", str(tmp_path / "manifest.json"), flag])
    with pytest.raises(SystemExit):
        replacer.main()
    replacer.session_factory.assert_not_called()


@pytest.fixture
def system_uploader(monkeypatch):
    storage = ModuleType("app.storage")
    storage.get_storage = Mock(return_value=SimpleNamespace(put_bytes=AsyncMock()))
    monkeypatch.setitem(sys.modules, "app.storage", storage)
    monkeypatch.setattr("dotenv.load_dotenv", Mock())
    return _load_script("sync-system-human-assets")


@pytest.mark.parametrize("size", [(1024, 1536), (2048, 3072)])
async def test_system_upload_preserves_original_resolution_and_portrait_thumbnail(system_uploader, tmp_path, size):
    path = tmp_path / "031.png"
    path.write_bytes(_image_bytes(size))

    await system_uploader.upload_assets([("031", path)])

    system_uploader.get_storage.assert_called_once_with()
    calls = system_uploader.get_storage.return_value.put_bytes.await_args_list
    assert len(calls) == 2
    for call, expected_key, expected_size in zip(
        calls,
        ["system/digital-humans/031.jpg", "system/digital-humans/thumbnails/031.jpg"],
        [size, (320, 480)],
    ):
        key, content, content_type = call.args
        assert key == expected_key
        assert content_type == "image/jpeg"
        with Image.open(io.BytesIO(content)) as image:
            assert image.size == expected_size
            assert image.format == "JPEG"
            assert image.mode == "RGB"


def test_system_upload_jpeg_applies_exif_before_optional_thumbnail(system_uploader, tmp_path):
    path = tmp_path / "031.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (1536, 1024), "gray").save(path, format="JPEG", exif=exif)

    for size, expected in [(None, (1024, 1536)), ((320, 480), (320, 480))]:
        with Image.open(io.BytesIO(system_uploader.jpeg_bytes(path, size, 88))) as image:
            assert image.size == expected
    system_uploader.get_storage.assert_not_called()


def test_system_upload_cli_describes_headshots(system_uploader, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["sync-system-human-assets.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        system_uploader.main()
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "headshots" in help_text
    assert "original-resolution" in help_text
    assert "sheets" not in help_text
    system_uploader.get_storage.assert_not_called()


def test_system_upload_missing_headshots_fails_before_storage(system_uploader, tmp_path):
    with pytest.raises(SystemExit, match="Expected character headshots 001–032"):
        system_uploader.directory_assets(tmp_path)
    system_uploader.get_storage.assert_not_called()
