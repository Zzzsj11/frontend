"""User portal; no endpoint can mint or bind an API key."""

import asyncio
import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .credits import account, default_rule, job_bill, ledger_view, lock, rules
from .db import Audit, Client, Job, Ledger, Model, Session, User, UserSession, now
from .status import public_status

router = APIRouter(prefix="/portal", tags=["User portal"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=10, max_length=128)


def password_hash(value, salt=None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + hashed


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
            raise HTTPException(429, "Too many attempts; retry after ten minutes")
        db.add(Audit(id=uuid.uuid4().hex, actor="anonymous", action=action, target=peer, detail={}))


@router.post("/register", status_code=201)
async def register(body: Credentials, request: Request):
    await throttle(request, "portal.register")
    hashed = await asyncio.to_thread(password_hash, body.password)
    async with Session.begin() as db:
        user = User(id="user-" + uuid.uuid4().hex, username=body.username.lower(), password_hash=hashed)
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            raise HTTPException(409, "Username unavailable") from None
    return {"id": user.id, "username": user.username, "message": "注册成功，请等待管理员生成并绑定 API Key"}


@router.post("/login")
async def login(body: Credentials, request: Request):
    await throttle(request, "portal.login")
    async with Session.begin() as db:
        user = await db.scalar(select(User).where(User.username == body.username.lower(), User.deleted_at.is_(None)))
        stored = user.password_hash if user else "00" * 16 + ":" + "00" * 64
        candidate = await asyncio.to_thread(password_hash, body.password, stored.split(":")[0])
        if not user or not user.enabled or not hmac.compare_digest(stored, candidate):
            raise HTTPException(401, "Invalid credentials")
        token = secrets.token_urlsafe(40)
        db.add(UserSession(id=uuid.uuid4().hex, user_id=user.id, token_hash=token_hash(token), expires_at=now() + timedelta(hours=8)))
    return {"access_token": token, "expires_in": 28800, "user": {"id": user.id, "username": user.username}}


async def current_user(request: Request):
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    async with Session() as db:
        session = await db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token), UserSession.deleted_at.is_(None)))
        if not session or session.expires_at.replace(tzinfo=timezone.utc) <= now():
            raise HTTPException(401, "Login required")
        user = await db.get(User, session.user_id)
        if not user or not user.enabled or user.deleted_at:
            raise HTTPException(401, "Login required")
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request, user=Depends(current_user)):
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
async def me(user=Depends(current_user)):
    async with Session.begin() as db:
        await lock(db)
        clients = (await db.scalars(select(Client).where(Client.user_id == user.id, Client.deleted_at.is_(None)))).all()
        accounts = [await account(db, c) for c in clients]
    return {"id": user.id, "username": user.username, "keys": accounts}


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
