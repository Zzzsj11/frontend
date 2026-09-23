import json
import runpy
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import Base, DigitalHumanModel

SCRIPT = Path(__file__).parents[2] / "scripts/prepare-headshot-migration.py"


def test_generated_asset_migration_applies_once_and_rejects_stale_or_private():
    compile_mapping = runpy.run_path(str(SCRIPT))["compile_mapping"]
    engine = sa.create_engine("sqlite:///:memory:")
    table = DigitalHumanModel.__table__
    with engine.begin() as db:
        Base.metadata.create_all(db)
        db.execute(
            table.insert().values(
                id="dh-system-test",
                name="fixture",
                scope="system",
                user_id=None,
                avatar_url="https://tos.test/old.jpg",
                created_at=datetime(2020, 1, 1),
                updated_at=datetime(2020, 1, 1),
            )
        )
        old = dict(db.execute(sa.select(table)).mappings().one())
        old = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in old.items()}
        updates = {k: "" for k in runpy.run_path(str(SCRIPT))["FIELDS"]}
        updates.update(avatar_url="https://tos.test/new.jpg", avatar_thumbnail_url="https://tos.test/thumb.jpg", asset_avatar_url="asset://fixture", description="identity only")
        document = {
            "schema_version": 1,
            "status": "prepared",
            "committed": False,
            "humans": [{"id": old["id"], "status": "prepared", "provider": "yinghe", "expected_old": old, "updates": updates}],
        }
        source = compile_mapping(document, "fixture_revision", "fixture_parent")
        module = ModuleType("fixture")
        exec(compile(source, "generated_migration", "exec"), module.__dict__)
        db.execute(table.update().values(description="concurrent edit"))
        with Operations.context(MigrationContext.configure(db)), pytest.raises(RuntimeError, match="Stale"):
            module.upgrade()
        assert db.scalar(sa.select(table.c.avatar_url)) == old["avatar_url"]
        db.execute(table.update().values(description=old["description"], updated_at=datetime.fromisoformat(old["updated_at"])))
        with Operations.context(MigrationContext.configure(db)):
            module.upgrade()
        assert db.scalar(sa.select(table.c.avatar_url)) == updates["avatar_url"]
        stamp = db.scalar(sa.select(table.c.updated_at))
        with Operations.context(MigrationContext.configure(db)):
            module.upgrade()
        assert db.scalar(sa.select(table.c.updated_at)) == stamp
        db.execute(table.update().values(scope="private"))
        with Operations.context(MigrationContext.configure(db)), pytest.raises(RuntimeError, match="active system"):
            module.upgrade()
    engine.dispose()
    bad = json.loads(json.dumps(document))
    bad["humans"][0]["expected_old"]["scope"] = "private"
    with pytest.raises(ValueError, match="Private"):
        compile_mapping(bad, "fixture_revision", "fixture_parent")
