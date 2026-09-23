"""Apply the user-selected catalog. Disable only; never grant provider permissions."""

import asyncio
import json
import uuid
from pathlib import Path

from gateway.db import Audit, Model, Session
from sqlalchemy import select


async def main():
    selection = json.loads((Path(__file__).resolve().parents[1] / "catalog/selected-models.json").read_text())
    disabled = []
    active = []
    async with Session.begin() as db:
        rows = (await db.scalars(select(Model).where(Model.deleted_at.is_(None)))).all()
        for model in rows:
            keep = model.provider_model in selection.get(model.kind, [])
            model.capabilities = {**model.capabilities, "catalog_selected": keep}
            if not keep and model.enabled:
                model.enabled = False
                disabled.append(model.id)
            if model.enabled:
                active.append(model.id)
        db.add(
            Audit(
                id=uuid.uuid4().hex,
                actor="code-agent",
                action="catalog.select_models",
                target="model-catalog",
                detail={"selection": selection, "disabled": disabled, "preserve_existing_disabled": True},
            )
        )
    print(json.dumps({"selected_unique": sum(map(len, selection.values())), "disabled": disabled, "active": active}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
