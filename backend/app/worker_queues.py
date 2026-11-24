"""Routing shared by job dispatch, database claims and lease recovery."""

from sqlalchemy import case, func

from .models import GenerationJobModel as JobRow

VIDEO_POOLS = {
    "video:wan": "all-in-one:wan3.0-video",
    "video:seedance": "all-in-one:doubao-seedance-2.0",
}
VIDEO_QUEUES = (*VIDEO_POOLS, "video:other")


def pool_name(request):
    return (
        {
            "wan3.0-video-all-in-one": VIDEO_POOLS["video:wan"],
            "doubao-seedance-2.0-all-in-one": VIDEO_POOLS["video:seedance"],
        }.get(request.get("model"))
        or request.get("_executionPool")
        or ""
    )


def pool_column():
    model = JobRow.request["model"].as_string()
    return case(
        (model == "wan3.0-video-all-in-one", VIDEO_POOLS["video:wan"]),
        (model == "doubao-seedance-2.0-all-in-one", VIDEO_POOLS["video:seedance"]),
        else_=func.coalesce(JobRow.request["_executionPool"].as_string(), ""),
    )


def queue_for(kind, request):
    if kind != "video":
        return kind
    pool = pool_name(request or {})
    return next((queue for queue, value in VIDEO_POOLS.items() if value == pool), "video:other")


def queue_conditions(kinds, providers, queue):
    conditions = [JobRow.kind.in_(kinds)]
    if providers:
        conditions.append(func.coalesce(JobRow.request["_provider"].as_string(), "internal").in_(providers))
    if queue == "video:other":
        conditions.append(pool_column().not_in(VIDEO_POOLS.values()))
    elif queue:
        conditions.append(pool_column() == VIDEO_POOLS[queue])
    return conditions
