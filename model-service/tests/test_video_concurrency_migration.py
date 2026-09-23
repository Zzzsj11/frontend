import sqlalchemy as sa
from test_supplier_retirement_migration import alembic, snapshot


def test_video_limits_scope_and_manual_override_survive(tmp_path):
    database = tmp_path / "limits.db"
    alembic(database, "upgrade", "0009")
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as db:
            before = snapshot(db, "model_routes")
            models = snapshot(db, "models")
        alembic(database, "upgrade", "head")
        limits = {
            "dreamina-seedance-2.0": 50,
            "dreamina-seedance-2.0-mini": 50,
            "dreamina-seedance-2.0-fast": 50,
            "wan3.0-video-sg": 100,
            "wan3.0-video-prime-sg": 100,
            "gemini-omni-flash-preview": 8,
        }
        with engine.begin() as db:
            after = snapshot(db, "model_routes")
            changed = []
            for rid, row in before.items():
                if row["supplier"] == "yseeai" and row["model_id"] in limits and not row["deleted_at"]:
                    assert after[rid]["concurrency"] == limits[row["model_id"]]
                    assert after[rid]["enabled"] == row["enabled"]
                    assert after[rid]["verification"] == row["verification"]
                    changed.append(rid)
                else:
                    assert after[rid] == row
            assert len(changed) == 6
            assert snapshot(db, "models") == models
            assert len([r for r in snapshot(db, "audits").values() if r["actor"] == "migration:0010"]) == 6
            db.execute(sa.text("UPDATE model_routes SET concurrency=150 WHERE id=:id"), {"id": changed[0]})
        alembic(database, "upgrade", "head")
        with engine.connect() as db:
            assert snapshot(db, "model_routes")[changed[0]]["concurrency"] == 150
    finally:
        engine.dispose()
