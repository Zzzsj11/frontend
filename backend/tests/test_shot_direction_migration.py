"""Published prompt upgrade preserves custom content, drafts and history."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.models import Base, PromptTemplateModel, PromptVersionModel
from app.video_prompt_policy import CHARACTER_DIRECTION_RULE


def test_shot_direction_migration_preserves_history_and_is_idempotent():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    migration = scripts.get_revision("a8c4e2f6b109").module
    assert scripts.get_heads() == [migration.revision]
    assert migration.down_revision == "e7a3b9c2f104"
    assert migration.DATA["policy"] == CHARACTER_DIRECTION_RULE
    templates, versions = PromptTemplateModel.__table__, PromptVersionModel.__table__
    engine = sa.create_engine("sqlite:///:memory:")
    stamp = datetime.now(timezone.utc)
    original = "五官、脸型、肤色、年龄感和发型必须严格一致。不得临时改为空镜、替换人物或引入其他人物。保留运营规则：不得泄露隐私。"
    with engine.begin() as conn:
        Base.metadata.create_all(conn, tables=[templates, versions])
        conn.execute(
            templates.insert().values(
                id="t",
                key="story_bible.ass.character_policy",
                name="运营标题",
                engine="llm",
                format="text",
                variables={},
                required_fragments=["严格一致", "不得泄露隐私"],
                current_version_id=None,
                created_at=stamp,
                updated_at=stamp,
            )
        )
        for ident, number, status in [("published", 2, "published"), ("draft", 9, "draft")]:
            conn.execute(
                versions.insert().values(id=ident, template_id="t", version=number, content=original, status=status, change_note="original", created_at=stamp, updated_at=stamp)
            )
        conn.execute(templates.update().values(current_version_id="published"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()
        rows = conn.execute(sa.select(versions).order_by(versions.c.version)).mappings().all()
        assert len(rows) == 3
        assert rows[0]["content"] == original and rows[0]["status"] == "archived"
        assert rows[1]["content"] == original and rows[1]["status"] == "draft"
        assert rows[2]["version"] == 10 and rows[2]["status"] == "published"
        assert "不得泄露隐私" in rows[2]["content"]
        assert "年龄感和发型" not in rows[2]["content"]
        assert CHARACTER_DIRECTION_RULE in rows[2]["content"]
        assert all(row["deleted_at"] is None for row in rows)
        template = conn.execute(sa.select(templates)).mappings().one()
        assert template["name"] == "运营标题"
        assert template["current_version_id"] == rows[2]["id"]
        with pytest.raises(RuntimeError, match="Invalid published prompt"):
            migration.transform("storyboard_line.requirements", "{}")
    engine.dispose()
