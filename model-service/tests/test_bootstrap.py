"""首次发布文件契约；无 Docker、数据库或真实凭据操作。"""

import importlib.util
import stat
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url


def bootstrap():
    spec = importlib.util.spec_from_file_location("bootstrap_mv", Path(__file__).parents[1] / "scripts/bootstrap-mv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_environment_uses_docker_literal_values(tmp_path):
    module = bootstrap()
    path = tmp_path / ".env.migration"
    url = "postgresql+asyncpg://model_migration:synthetic%24%23%40@postgres:5432/model_service"
    module.write_private(path, {"DATABASE_URL": url, "LLM_MODEL": "gpt-5.6-sol"})
    # docker run 的 env-file 逐行解析，值不会去引号或做 shell 展开。
    values = dict(line.split("=", 1) for line in path.read_text().splitlines())
    assert values["DATABASE_URL"] == url
    assert make_url(values["DATABASE_URL"]).database == "model_service"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        module.write_private(path, {"DATABASE_URL": "must-not-overwrite"})
    assert path.read_text().startswith("DATABASE_URL=" + url + "\n")


def test_runtime_environment_still_protects_compose_interpolation(tmp_path):
    module = bootstrap()
    path = tmp_path / ".env.public"
    module.write_private(path, {"SYNTHETIC_KEY": "dollar$literal#suffix"})
    assert path.read_text() == "SYNTHETIC_KEY='dollar$literal#suffix'\n"
    assert module.migration_head() == "0008"
