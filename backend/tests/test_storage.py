import pytest

from app.storage import download_public_url, safe_key


def test_safe_key_removes_path_traversal() -> None:
    key = safe_key("../../images", "../../avatar 中文.png")
    assert ".." not in key
    assert key.startswith("images/")
    assert key.endswith(".png")


def test_safe_key_supports_user_scoped_tos_paths() -> None:
    key = safe_key("users/user-1/projects/project-1", "scene.png")
    assert key.startswith("users/user-1/projects/project-1/")


@pytest.mark.asyncio
async def test_remote_import_rejects_local_and_plain_http_urls() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        await download_public_url("http://127.0.0.1/private.png")
