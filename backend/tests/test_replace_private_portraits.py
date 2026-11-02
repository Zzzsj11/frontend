import copy
from dataclasses import replace

import pytest
import sqlalchemy as sa

from app import storage
from app.models import AdminOperationLogModel, Base, DigitalHumanModel
from scripts.replace_private_portraits import apply


@pytest.fixture
def portrait_db(monkeypatch):
    monkeypatch.setattr(storage, "settings", replace(storage.settings, tos_public_domain="owned.test"))
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            DigitalHumanModel.__table__.insert().values(
                id="portrait", user_id="owner", scope="private", name="Original label", avatar_url="https://owned.test/users/owner/old.jpg", avatar_thumbnail_url=None
            )
        )
    yield engine
    engine.dispose()


def manifest():
    return {
        "user_id": "owner",
        "run_id": "test-run",
        "items": [
            {
                "id": "portrait",
                "platform_job_id": "job-synthetic",
                "before": {"avatar_url": "https://owned.test/users/owner/old.jpg", "avatar_thumbnail_url": None},
                "after": {"avatar_url": "https://owned.test/users/owner/new.png", "avatar_thumbnail_url": "https://owned.test/users/owner/new-thumb.jpg"},
            }
        ],
    }


def test_replace_retains_label_and_before_image_and_is_idempotent(portrait_db):
    with portrait_db.begin() as connection:
        assert apply(connection, manifest()) == 1
        assert apply(connection, manifest()) == 0
        row = connection.execute(sa.select(DigitalHumanModel.__table__)).mappings().one()
        assert row["name"] == "Original label"
        log = connection.execute(sa.select(AdminOperationLogModel.__table__)).mappings().one()
        assert log["before_data"] == manifest()["items"][0]["before"]
        assert log["after_data"]["agent_name"] == "code-agent"
        assert log["after_data"]["platform_job_id"] == "job-synthetic"


@pytest.mark.parametrize("problem", ["owner", "system", "stale", "foreign-media"])
def test_replace_rejects_wrong_scope_or_newer_asset(portrait_db, problem):
    request = copy.deepcopy(manifest())
    with portrait_db.begin() as connection:
        if problem == "owner":
            request["user_id"] = "other"
        elif problem == "system":
            connection.execute(DigitalHumanModel.__table__.update().values(scope="system"))
        elif problem == "stale":
            request["items"][0]["before"]["avatar_url"] = "https://owned.test/users/owner/stale.jpg"
        else:
            request["items"][0]["after"]["avatar_url"] = "https://owned.test/users/other/private.jpg"
        with pytest.raises(ValueError):
            apply(connection, request)
        assert connection.scalar(sa.select(sa.func.count()).select_from(AdminOperationLogModel.__table__)) == 0
