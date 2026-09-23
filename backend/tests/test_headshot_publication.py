import json

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from test_headshot_prompt_migration import KEY, TEMPLATES, VERSIONS, _insert_template, _scripts, connection  # noqa: F401


def test_publication_preserves_custom_content_and_drafts(connection):  # noqa: F811
    metadata = _scripts().get_revision("d6f2a8c1e903").module
    publication = _scripts().get_revision("e7a3b9c2f104").module
    _insert_template(connection, current_version_id="portrait-published")
    current = connection.execute(sa.select(VERSIONS).where(VERSIONS.c.id == "portrait-published")).mappings().one()
    connection.execute(VERSIONS.update().where(VERSIONS.c.id == current["id"]).values(content=current["content"] + "运营补充：不得泄露隐私。"))
    with Operations.context(MigrationContext.configure(connection)):
        metadata.upgrade()
        publication.upgrade()
    pointer = connection.scalar(sa.select(TEMPLATES.c.current_version_id).where(TEMPLATES.c.key == KEY))
    row = connection.execute(sa.select(VERSIONS).where(VERSIONS.c.id == pointer)).mappings().one()
    assert "单人正面头肩大头照" in row["content"] and row["content"].endswith("运营补充：不得泄露隐私。")
    assert row["version"] == 5  # Includes the previously soft-deleted draft.
    assert connection.scalar(sa.select(VERSIONS.c.status).where(VERSIONS.c.id == current["id"])) == "archived"
    count = connection.scalar(sa.select(sa.func.count()).select_from(VERSIONS))
    with Operations.context(MigrationContext.configure(connection)):
        publication.upgrade()
    assert connection.scalar(sa.select(sa.func.count()).select_from(VERSIONS)) == count


def test_unknown_custom_base_is_not_overwritten():
    publication = _scripts().get_revision("e7a3b9c2f104").module
    with pytest.raises(RuntimeError, match="explicit merge"):
        publication.transform(KEY, "完全不同的运营定制模板")
    key = "storyboard_line.requirements"
    old, new = publication.DATA[key]["replacements"][0]
    result = json.loads(publication.transform(key, json.dumps(["运营自定义", old], ensure_ascii=False)))
    assert result == ["运营自定义", new]
