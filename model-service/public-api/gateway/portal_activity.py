"""Paginated account activity: each job once, plus non-job ledger entries."""

from decimal import Decimal

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import load_only

from .credits import ledger_view
from .db import Client, Job, Ledger
from .status import public_status


async def activity(db, uid, page, limit, client_id, kind):
    owned = select(Client.id).where(Client.user_id == uid)
    jobs = select(Job).where(Job.user_id == uid, Job.deleted_at.is_(None), Job.client_id.in_(owned))
    ledger = select(Ledger).where(Ledger.user_id == uid, Ledger.deleted_at.is_(None), Ledger.client_id.in_(owned))
    standalone = ledger.where((Ledger.job_id.is_(None)) | (~Ledger.job_id.in_(jobs.with_only_columns(Job.id))))
    if client_id:
        jobs = jobs.where(Job.client_id == client_id)
        standalone = standalone.where(Ledger.client_id == client_id)
    if kind:
        if kind == "generation":
            standalone = standalone.where(literal(False))
        else:
            standalone = standalone.where(Ledger.kind == kind)
            jobs = jobs.where(Job.id.in_(ledger.where(Ledger.kind == kind).with_only_columns(Ledger.job_id)))
    combined = union_all(
        jobs.with_only_columns(Job.id.label("id"), Job.created_at.label("time"), literal("job").label("type")),
        standalone.with_only_columns(Ledger.id.label("id"), Ledger.created_at.label("time"), literal("ledger").label("type")),
    ).subquery()
    total = await db.scalar(select(func.count()).select_from(combined))
    limit = max(1, min(limit, 100))
    page = max(1, min(page, max(1, (total + limit - 1) // limit)))
    rows = (
        await db.execute(
            select(combined).order_by(combined.c.time.desc(), combined.c.id.desc(), combined.c.type).offset((page - 1) * limit).limit(limit)
        )
    ).all()
    job_ids = [r.id for r in rows if r.type == "job"]
    ledger_ids = [r.id for r in rows if r.type == "ledger"]
    summary_jobs = jobs.where(Job.id.in_(job_ids)).options(
        load_only(
            Job.id,
            Job.client_id,
            Job.created_at,
            Job.kind,
            Job.model_id,
            Job.status,
            Job.charged_points,
            Job.reserved_points,
            Job.billing_status,
        )
    )
    job_map = {j.id: j for j in (await db.scalars(summary_jobs)).all()}
    ledger_map = {entry.id: entry for entry in (await db.scalars(standalone.where(Ledger.id.in_(ledger_ids)))).all()}
    sums = dict(
        (
            await db.execute(
                ledger.where(Ledger.job_id.in_(job_ids)).with_only_columns(Ledger.job_id, func.sum(Ledger.points)).group_by(Ledger.job_id)
            )
        ).all()
    )
    ranked = (
        ledger.where(Ledger.job_id.in_(job_ids))
        .with_only_columns(
            Ledger.job_id,
            Ledger.monthly_after,
            Ledger.extra_after,
            func.row_number().over(partition_by=Ledger.job_id, order_by=(Ledger.created_at.desc(), Ledger.id.desc())).label("rank"),
        )
        .subquery()
    )
    balances = {r.job_id: r for r in (await db.execute(select(ranked).where(ranked.c.rank == 1))).all()}
    names = dict((await db.execute(select(Client.id, Client.name).where(Client.user_id == uid))).all())
    items = []
    for row in rows:
        if row.type == "ledger":
            item = {**ledger_view(ledger_map[row.id]), "job_id": None, "status": "", "model": "", "task_kind": ""}
        else:
            job = job_map[row.id]
            value = sums.get(job.id)
            # Without a settlement, do not turn an unknown charge into zero.
            points = str(value) if value is not None else str(-Decimal(job.charged_points)) if job.charged_points is not None else None
            item = {
                "id": job.id,
                "job_id": job.id,
                "client_id": job.client_id,
                "created_at": job.created_at,
                "kind": "generation",
                "task_kind": job.kind,
                "model": job.model_id,
                "status": public_status(job.status),
                "points": points,
                "monthly_after": str(balances[job.id].monthly_after) if job.id in balances else None,
                "extra_after": str(balances[job.id].extra_after) if job.id in balances else None,
                "reason": job.model_id,
                "evidence": {},
                "reserved_points": str(job.reserved_points or 0),
                "billing_status": job.billing_status,
            }
        items.append({**item, "key_name": names.get(item["client_id"], "已删除 Key"), "row_type": row.type})
    return {"items": items, "total": total, "page": page, "limit": limit}
