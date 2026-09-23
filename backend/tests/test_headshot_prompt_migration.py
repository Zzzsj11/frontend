"""Verify metadata-only migration and publishing validation on isolated in-memory SQLite."""

from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import HTTPException

from app.admin import _validate_prompt_content
from app.models import Base, PromptTemplateModel, PromptVersionModel
from app.prompts import DEFAULT_PROMPTS

ROOT = Path(__file__).resolve().parents[1]
REVISION = "d6f2a8c1e903"
PREVIOUS = "b3f7a1c5e902"
KEY = "portrait.digital_human_ref"
TEMPLATES = PromptTemplateModel.__table__
VERSIONS = PromptVersionModel.__table__
CREATED = datetime(2020, 1, 1)
UPDATED = datetime(2021, 2, 3)
DELETED = datetime(2022, 3, 4)
LEGACY_METADATA = {
    "name": "数字人定妆照提示词",
    "description": "数字人三视图定妆照的图生图提示词模板；extra 段由后端按描述/风格拼装。",
    "variables": {"extra": "角色描述与画面风格附加段（代码拼装，可为空串）"},
    "required_fragments": ["第一张参考图", "第二张参考图", "禁止继承"],
}
LEGACY_CONTENT = (
    "第一张参考图只定义身份参考卡的构图版式：中性灰背景，左侧大幅正面头肩像，右侧依次排列头部正面/侧面/背面和全身正面/侧面/背面，"
    "棚拍柔光，清晰写实。第二张参考图只定义人物身份：必须保持其五官、脸型、肤色、年龄感、发型和身体比例一致。"
    "所有人物统一穿纯白无图案圆领短袖T恤与中性浅灰下装，不佩戴饰品，不持道具。"
    "禁止继承任一参考图中的原服装、配饰、职业、年代、场景、文字、Logo或水印。{{extra}}"
    "附加描述只可影响人物身份特征，不得改变统一服装、背景与排版。"
)
CUSTOM_FRAGMENTS = ["不得泄露用户隐私", "禁止从第一张参考图提取证件号码", "不得保留第二张参考图中的联系方式"]
CUSTOM_VARIABLES = {"operator_note": "已有运营扩展变量，不由迁移删除"}


def _scripts():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


@pytest.fixture
def migration():
    return _scripts().get_revision(REVISION).module


@pytest.fixture
def connection():
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            Base.metadata.create_all(conn, tables=[TEMPLATES, VERSIONS])
            yield conn
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def _run(connection, migration, direction="upgrade"):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, direction)()


def _insert_template(connection, template_id="portrait", **overrides):
    values = {
        "id": template_id,
        "key": KEY,
        **LEGACY_METADATA,
        "engine": "image",
        "format": "text",
        "status": "active",
        "current_version_id": f"{template_id}-published",
        "created_at": CREATED,
        "updated_at": UPDATED,
        "deleted_at": None,
        **overrides,
    }
    connection.execute(TEMPLATES.insert().values(**values))
    # Include archived/published versions, an operator draft and a deleted draft.
    for number, status in enumerate(("archived", "published", "draft", "deleted-draft"), start=1):
        connection.execute(
            VERSIONS.insert().values(
                id=f"{template_id}-{status}",
                template_id=template_id,
                version=number,
                content=LEGACY_CONTENT if status == "published" else f"运营定制正文（{status}）：不得覆盖",
                status="draft" if status == "deleted-draft" else status,
                change_note=f"运营备注 {number}",
                created_by="operator",
                published_at=UPDATED if status in {"published", "archived"} else None,
                created_at=CREATED,
                updated_at=UPDATED,
                deleted_at=DELETED if status == "deleted-draft" else None,
            )
        )


def _template(connection):
    return dict(connection.execute(sa.select(TEMPLATES).where(TEMPLATES.c.key == KEY)).mappings().one())


def _snapshot(connection, table):
    # Raw snapshots detect writes to any column, including timestamps and JSON.
    return [dict(row) for row in connection.execute(sa.text(f"SELECT * FROM {table.name} ORDER BY id")).mappings()]


def test_revision_lineage_and_frozen_metadata(migration):
    assert _scripts().get_revision("e7a3b9c2f104").down_revision == REVISION
    assert migration.down_revision == PREVIOUS
    assert migration.LEGACY_METADATA == LEGACY_METADATA
    assert migration.HEADSHOT_METADATA == {field: DEFAULT_PROMPTS[KEY][field] for field in LEGACY_METADATA}


@pytest.mark.parametrize("current_version_id", ["portrait-published", None])
def test_upgrade_legacy_metadata_only(connection, migration, current_version_id):
    _insert_template(connection, current_version_id=current_version_id, status="disabled")
    before = _template(connection)
    versions_before = _snapshot(connection, VERSIONS)
    _run(connection, migration)
    after = _template(connection)
    assert after == {
        **before,
        **{field: DEFAULT_PROMPTS[KEY][field] for field in LEGACY_METADATA},
        "updated_at": after["updated_at"],
    }
    assert after["updated_at"] > UPDATED
    assert _snapshot(connection, VERSIONS) == versions_before


def test_preserve_custom_constraints_and_variables(connection, migration):
    _insert_template(
        connection,
        name="运营自定义名称",
        description="旧说明",
        variables={"extra": "旧的定制描述", **CUSTOM_VARIABLES},
        required_fragments=[*LEGACY_METADATA["required_fragments"], *CUSTOM_FRAGMENTS, "中性灰"],
    )
    versions_before = _snapshot(connection, VERSIONS)
    _run(connection, migration)
    after = _template(connection)
    assert after["name"] == DEFAULT_PROMPTS[KEY]["name"]
    assert after["description"] == DEFAULT_PROMPTS[KEY]["description"]
    assert after["variables"] == {**DEFAULT_PROMPTS[KEY]["variables"], **CUSTOM_VARIABLES}
    assert after["required_fragments"] == [*DEFAULT_PROMPTS[KEY]["required_fragments"], *CUSTOM_FRAGMENTS]
    assert _snapshot(connection, VERSIONS) == versions_before
    # Custom safety rules still block publishing until operators include them.
    template = PromptTemplateModel(**after)
    with pytest.raises(HTTPException, match="不得泄露用户隐私") as exc:
        _validate_prompt_content(template, DEFAULT_PROMPTS[KEY]["content"])
    assert exc.value.status_code == 422
    _validate_prompt_content(template, DEFAULT_PROMPTS[KEY]["content"] + "；".join(CUSTOM_FRAGMENTS) + "{{operator_note}}")


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_soft_deleted_and_other_templates_unchanged(connection, migration, direction):
    _insert_template(connection, deleted_at=DELETED)
    for key in ("storyboard_line.requirements", "story_bible.general.character_policy", "portrait.digital_human_ref.custom"):
        _insert_template(connection, template_id=key, key=key)
    before = {table.name: _snapshot(connection, table) for table in (TEMPLATES, VERSIONS)}
    _run(connection, migration, direction)
    assert {table.name: _snapshot(connection, table) for table in (TEMPLATES, VERSIONS)} == before


def test_empty_database_does_not_create_templates_or_versions(connection, migration):
    _run(connection, migration)
    _run(connection, migration, "downgrade")
    assert _snapshot(connection, TEMPLATES) == []
    assert _snapshot(connection, VERSIONS) == []


def test_repeated_upgrade_is_stable_including_timestamp(connection, migration):
    _insert_template(
        connection,
        variables={**LEGACY_METADATA["variables"], **CUSTOM_VARIABLES},
        required_fragments=[*LEGACY_METADATA["required_fragments"], *CUSTOM_FRAGMENTS],
    )
    _run(connection, migration)
    before = {table.name: _snapshot(connection, table) for table in (TEMPLATES, VERSIONS)}
    _run(connection, migration)
    assert {table.name: _snapshot(connection, table) for table in (TEMPLATES, VERSIONS)} == before


def test_new_defaults_publish_without_first_or_second_reference(connection, migration):
    _insert_template(connection)
    content = DEFAULT_PROMPTS[KEY]["content"]
    assert "第一张参考图" not in content and "第二张参考图" not in content
    with pytest.raises(HTTPException, match="第一张参考图.*第二张参考图") as exc:
        _validate_prompt_content(PromptTemplateModel(**_template(connection)), content)
    assert exc.value.status_code == 422
    _run(connection, migration)
    template = PromptTemplateModel(**_template(connection))
    _validate_prompt_content(template, content)
    # Validate every new safety fragment, not only the retired two-image rule.
    for fragment in DEFAULT_PROMPTS[KEY]["required_fragments"]:
        with pytest.raises(HTTPException, match="缺少必含安全片段") as exc:
            _validate_prompt_content(template, content.replace(fragment, ""))
        assert exc.value.status_code == 422
    with pytest.raises(HTTPException, match="模板变量未声明"):
        _validate_prompt_content(template, content + "{{undeclared}}")
    with pytest.raises(HTTPException, match="缺少必含安全片段"):
        _validate_prompt_content(template, LEGACY_CONTENT)
    # This is the existing pure validator, not a publish API/model invocation.
    assert _template(connection)["current_version_id"] == "portrait-published"


def test_downgrade_restores_legacy_base_and_preserves_operator_additions(connection, migration):
    _insert_template(
        connection,
        variables={**LEGACY_METADATA["variables"], **CUSTOM_VARIABLES},
        required_fragments=[*LEGACY_METADATA["required_fragments"], *CUSTOM_FRAGMENTS],
    )
    versions_before = _snapshot(connection, VERSIONS)
    original = _template(connection)
    _run(connection, migration)
    # Also preserve constraints introduced by an operator after upgrading.
    upgraded = _template(connection)
    extra_rule = "不得推断用户住址"
    variables = {**upgraded["variables"], "review_note": "升级后运营增加的变量"}
    connection.execute(TEMPLATES.update().where(TEMPLATES.c.key == KEY).values(variables=variables, required_fragments=[*upgraded["required_fragments"], extra_rule]))
    _run(connection, migration, "downgrade")
    downgraded = _template(connection)
    assert downgraded == {
        **original,
        "variables": {**variables, **LEGACY_METADATA["variables"]},
        "required_fragments": [*LEGACY_METADATA["required_fragments"], *CUSTOM_FRAGMENTS, extra_rule],
        "updated_at": downgraded["updated_at"],
    }
    assert downgraded["updated_at"] > UPDATED
    assert _snapshot(connection, VERSIONS) == versions_before
    _validate_prompt_content(PromptTemplateModel(**downgraded), LEGACY_CONTENT + "；".join([*CUSTOM_FRAGMENTS, extra_rule]))
    snapshot = _snapshot(connection, TEMPLATES)
    _run(connection, migration, "downgrade")
    assert _snapshot(connection, TEMPLATES) == snapshot
    _run(connection, migration)
    assert _template(connection)["required_fragments"] == [*DEFAULT_PROMPTS[KEY]["required_fragments"], *CUSTOM_FRAGMENTS, extra_rule]
    assert _snapshot(connection, VERSIONS) == versions_before
