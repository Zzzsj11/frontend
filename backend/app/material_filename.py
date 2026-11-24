"""Browser download names for material archives."""

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DigitalHumanModel, ProjectCastModel, ProjectTaskModel, ShotAssetModel, StoryboardLineCastModel, StoryboardLineModel


def zip_filename(names: list[str], config: dict, task_title: str) -> str:
    categories = [config.get(key) for key in ("genre", "secondary_category", "tertiary_category")]
    for parts in (names, categories, [task_title]):
        stem = "-".join(value.strip() for value in parts if isinstance(value, str) and value.strip())
        stem = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "_", stem).strip(" .")
        stem = stem.encode("utf-8")[:240].decode("utf-8", "ignore").rstrip(" .")
        if stem:
            if re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", stem, re.I):
                stem = "_" + stem
            return stem + ".zip"
    return "素材.zip"


async def material_filename(db: AsyncSession, task: ProjectTaskModel, user_id: str) -> str:
    human = DigitalHumanModel
    visible = select(human.id, human.name).where(human.deleted_at.is_(None), or_(human.scope == "system", human.user_id == user_id))
    cast = await db.execute(
        visible.join(ProjectCastModel, ProjectCastModel.digital_human_id == human.id)
        .where(ProjectCastModel.project_task_id == task.id, ProjectCastModel.deleted_at.is_(None))
        .order_by(ProjectCastModel.sort_order, ProjectCastModel.id)
    )
    line = StoryboardLineModel
    role = StoryboardLineCastModel
    has_video = select(ShotAssetModel.id).where(ShotAssetModel.storyboard_line_id == line.id, ShotAssetModel.deleted_at.is_(None), ShotAssetModel.video_url != "").exists()
    line_cast = await db.execute(
        visible.join(role, role.digital_human_id == human.id)
        .join(line, role.storyboard_line_id == line.id)
        .where(line.project_task_id == task.id, line.deleted_at.is_(None), role.deleted_at.is_(None), has_video)
        .order_by(line.sort_order, line.id, role.sort_order, role.id)
    )
    names_by_id = dict([*cast, *line_cast])
    return zip_filename(list(names_by_id.values()), task.storyboard_config or {}, task.title)
