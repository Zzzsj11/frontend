"""Private user portal: administrators create accounts, users manage their own keys."""

import asyncio
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update

from .credits import (
    account,
    amount,
    configure_quota,
    default_rule,
    ensure_key_slot,
    job_bill,
    ledger_view,
    lock,
    reset,
    rules,
    user_account,
)
from .db import Audit, Client, Job, Ledger, Model, Session, User, UserSession, now
from .passwords import password_hash
from .status import public_status

router = APIRouter(prefix="/portal", tags=["User portal"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=8, max_length=128)


def validate_password(value):
    if not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value):
        raise ValueError("密码至少 8 位，且包含字母和数字")
    return value


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirmation: str = Field(min_length=8, max_length=128)
    _password_policy = field_validator("new_password")(validate_password)


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


async def throttle(request, action):
    peer = request.client.host if request.client else "unknown"
    async with Session.begin() as db:
        await lock(db)
        count = await db.scalar(
            select(func.count())
            .select_from(Audit)
            .where(Audit.action == action, Audit.target == peer, Audit.created_at > now() - timedelta(minutes=10))
        )
        if count >= (5 if action == "portal.register" else 20):
            raise HTTPException(429, "尝试次数过多，请 10 分钟后重试")
        db.add(Audit(id=uuid.uuid4().hex, actor="anonymous", action=action, target=peer, detail={}))


@router.post("/register")
async def register():
    raise HTTPException(403, "账号由管理员创建，请联系管理员")


@router.post("/login")
async def login(body: Credentials, request: Request):
    await throttle(request, "portal.login")
    async with Session.begin() as db:
        user = await db.scalar(select(User).where(User.username == body.username.lower(), User.deleted_at.is_(None)).with_for_update())
        stored = user.password_hash if user else "00" * 16 + ":" + "00" * 64
        candidate = await asyncio.to_thread(password_hash, body.password, stored.split(":")[0])
        if not user or not user.enabled or not hmac.compare_digest(stored, candidate):
            raise HTTPException(401, "邮箱或密码不正确")
        token = secrets.token_urlsafe(40)
        db.add(UserSession(id=uuid.uuid4().hex, user_id=user.id, token_hash=token_hash(token), expires_at=now() + timedelta(hours=8)))
    return {"access_token": token, "expires_in": 28800, "user": {"id": user.id, "username": user.username}}


async def authenticated_user(request: Request):
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    async with Session() as db:
        session = await db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token), UserSession.deleted_at.is_(None)))
        if not session or session.expires_at.replace(tzinfo=timezone.utc) <= now():
            raise HTTPException(401, "登录已失效，请重新登录")
        user = await db.get(User, session.user_id)
        if not user or not user.enabled or user.deleted_at:
            raise HTTPException(401, "登录已失效，请重新登录")
    return user


async def current_user(user=Depends(authenticated_user)):
    if user.password_changed_at is None:
        raise HTTPException(403, "首次登录请先修改密码")
    return user


@router.post("/change-password", status_code=204)
async def change_password(body: PasswordChange, request: Request, user=Depends(authenticated_user)):
    await throttle(request, "portal.change_password")
    if body.new_password != body.confirmation:
        raise HTTPException(400, "两次输入的新密码不一致")
    if body.new_password == body.current_password:
        raise HTTPException(400, "新密码不能与原密码相同")
    async with Session.begin() as db:
        row = await db.scalar(select(User).where(User.id == user.id).with_for_update())
        session = await db.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash(request.headers.get("authorization", "").removeprefix("Bearer ")),
                UserSession.user_id == user.id,
                UserSession.deleted_at.is_(None),
                UserSession.expires_at > now(),
            )
        )
        if not session or not row or not row.enabled or row.deleted_at:
            raise HTTPException(401, "登录已失效，请重新登录")
        candidate = await asyncio.to_thread(password_hash, body.current_password, row.password_hash.split(":")[0])
        if not hmac.compare_digest(row.password_hash, candidate):
            raise HTTPException(400, "原密码不正确")
        row.password_hash = await asyncio.to_thread(password_hash, body.new_password)
        row.password_changed_at = now()
        await db.execute(
            update(UserSession).where(UserSession.user_id == user.id, UserSession.deleted_at.is_(None)).values(deleted_at=now())
        )
        db.add(Audit(id=uuid.uuid4().hex, actor=user.id, action="portal.password_changed", target=user.id, detail={}))


@router.post("/logout", status_code=204)
async def logout(request: Request, user=Depends(authenticated_user)):
    async with Session.begin() as db:
        row = await db.scalar(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.token_hash == token_hash(request.headers.get("authorization", "").removeprefix("Bearer ")),
            )
        )
        if row:
            row.deleted_at = now()


@router.get("/me")
async def me(user=Depends(authenticated_user)):
    if user.password_changed_at is None:
        return {"id": user.id, "username": user.username, "must_change_password": True, "keys": []}
    async with Session.begin() as db:
        await lock(db)
        clients = (await db.scalars(select(Client).where(Client.user_id == user.id, Client.deleted_at.is_(None)))).all()
        accounts = [await account(db, c) for c in clients]
        owner = await db.get(User, user.id)
        limits = await user_account(db, owner)
    return {"id": user.id, "username": user.username, "must_change_password": False, "keys": accounts, "quota": limits}


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    monthly_points: Decimal = Field(ge=0, le=1000000000, decimal_places=6)


@router.post("/keys", status_code=201)
async def create_key(body: KeyCreate, user=Depends(current_user)):
    key = "ms_" + secrets.token_urlsafe(32)
    async with Session.begin() as db:
        await lock(db)
        await ensure_key_slot(db, user.id)
        c = Client(
            id="client-" + uuid.uuid4().hex,
            name=body.name,
            user_id=user.id,
            key_hash=token_hash(key),
            key_prefix=key[:12],
            enabled=True,
            billing_enabled=True,
            monthly_points=amount(body.monthly_points),
            monthly_balance=amount(0),
            extra_balance=amount(0),
            billing_month="",
        )
        db.add(c)
        await db.flush()
        await reset(db, c)
        db.add(
            Audit(
                id=uuid.uuid4().hex,
                actor=user.id,
                action="client.create",
                target=c.id,
                detail={"name": c.name, "user_id": user.id, "monthly_points": str(body.monthly_points)},
            )
        )
        return {**await account(db, c), "api_key": key}


@router.delete("/keys/{cid}", status_code=204)
async def delete_key(cid: str, user=Depends(current_user)):
    async with Session.begin() as db:
        await lock(db)
        c = await db.get(Client, cid)
        if not c or c.deleted_at or c.user_id != user.id:
            raise HTTPException(404, "Key 不存在")
        c.deleted_at, c.enabled = now(), False
        db.add(Audit(id=uuid.uuid4().hex, actor=user.id, action="client.delete", target=cid, detail={}))


class KeyQuota(BaseModel):
    points: Decimal = Field(ge=0, le=1000000000, decimal_places=6)


@router.post("/keys/{cid}/quota")
async def key_quota(cid: str, body: KeyQuota, user=Depends(current_user)):
    async with Session.begin() as db:
        await lock(db)
        c = await db.get(Client, cid)
        if not c or c.deleted_at or c.user_id != user.id:
            raise HTTPException(404, "Key 不存在")
        await configure_quota(db, c, body.points, user.id)
        db.add(
            Audit(
                id=uuid.uuid4().hex,
                actor=user.id,
                action="quota.configure",
                target=cid,
                detail={"monthly_points": str(body.points), "effect": "immediate"},
            )
        )
        return await account(db, c)


@router.get("/models")
async def models():
    async with Session() as db:
        rows = (await db.scalars(select(Model).where(Model.deleted_at.is_(None)).order_by(Model.kind, Model.id))).all()
        if any(m.capabilities.get("unified_catalog") for m in rows):
            rows = [m for m in rows if m.capabilities.get("unified_catalog")]
        return [
            {
                "id": m.id,
                "kind": m.kind,
                "enabled": m.enabled,
                "capabilities": m.capabilities,
                "pricing": await rules(db, m.id) or [default_rule(m)],
            }
            for m in rows
        ]


@router.get("/jobs")
async def jobs(page: int = 1, limit: int = 30, user=Depends(current_user)):
    limit = max(1, min(limit, 100))
    query = select(Job).where(
        Job.user_id == user.id, Job.deleted_at.is_(None), Job.client_id.in_(select(Client.id).where(Client.user_id == user.id))
    )
    async with Session() as db:
        total = await db.scalar(select(func.count()).select_from(query.subquery()))
        rows = (await db.scalars(query.order_by(Job.created_at.desc()).offset((max(1, page) - 1) * limit).limit(limit))).all()
    return {
        "total": total,
        "items": [
            {
                "id": j.id,
                "client_id": j.client_id,
                "model": j.model_id,
                "status": public_status(j.status),
                "usage": j.usage,
                "billing": job_bill(j),
                "created_at": j.created_at,
                "error": j.error,
            }
            for j in rows
        ],
    }


@router.get("/ledger")
async def ledger(page: int = 1, limit: int = 50, user=Depends(current_user)):
    limit = max(1, min(limit, 100))
    query = select(Ledger).where(Ledger.user_id == user.id, Ledger.deleted_at.is_(None))
    async with Session() as db:
        total = await db.scalar(select(func.count()).select_from(query.subquery()))
        rows = (await db.scalars(query.order_by(Ledger.created_at.desc()).offset((max(1, page) - 1) * limit).limit(limit))).all()
    return {"total": total, "items": [ledger_view(row) for row in rows]}
