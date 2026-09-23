import sqlalchemy as sa
from test_supplier_retirement_migration import alembic, snapshot


def test_optimizer_channels_retired_and_other_accounts_preserved(tmp_path):
    database = tmp_path / "optimizer-retirement.db"
    alembic(database, "upgrade", "0011")
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as db:
            before = snapshot(db, "channel_accounts")
            jobs = snapshot(db, "jobs")
            ledger = snapshot(db, "credit_ledger")
        alembic(database, "upgrade", "head")
        with engine.connect() as db:
            after = snapshot(db, "channel_accounts")
            for key, row in before.items():
                if row["channel"] in ("optimizer-gemini", "optimizer-minimax"):
                    assert after[key]["deleted_at"] is not None
                    assert after[key]["snapshot"] == row["snapshot"]
                else:
                    assert after[key] == row
            assert snapshot(db, "jobs") == jobs
            assert snapshot(db, "credit_ledger") == ledger
        alembic(database, "upgrade", "head")
        with engine.connect() as db:
            assert snapshot(db, "channel_accounts") == after
    finally:
        engine.dispose()
