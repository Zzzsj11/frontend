from pathlib import Path

from app.storage import LocalStorage, safe_key


def test_safe_key_removes_path_traversal() -> None:
    key = safe_key("../../images", "../../avatar 中文.png")
    assert ".." not in key
    assert key.startswith("images/")
    assert key.endswith(".png")


async def test_local_storage_writes_inside_media_root(tmp_path: Path) -> None:
    storage = LocalStorage()
    storage.root = tmp_path
    url = await storage.put_bytes("images/test.png", b"png", "image/png")
    assert url == "/media/images/test.png"
    assert (tmp_path / "images/test.png").read_bytes() == b"png"

