"""Database-backed administrator password and revocable access tokens."""

import asyncio
import hmac
import os
import re
import uuid
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from .credits import lock
from .db import AdminCredential, Audit, Session, now
from .passwords import password_hash

router = APIRouter(prefix="/admin")
SECRET = os.environ["ADMIN_JWT_SECRET"]
if len(SECRET) < 32:
    raise RuntimeError("ADMIN_JWT_SECRET must contain at least 32 characters")


def claims(request):
    try:
        return jwt.decode(
            request.headers.get("authorization", "").removeprefix("Bearer "),
            SECRET,
            algorithms=["HS256"],
            audience="model-control",
            options={"require": ["sub", "exp", "version"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "管理员登录已失效，请重新登录") from None


async def admin(request: Request):
    token = claims(request)
    async with Session() as db:
        row = await db.scalar(select(AdminCredential).where(AdminCredential.username == token["sub"]))
        if not row or row.deleted_at or row.auth_version != token["version"]:
            raise HTTPException(401, "管理员登录已失效，请重新登录")
        return row.username


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirmation: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def policy(cls, value):
        if not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value):
            raise ValueError("新密码至少 8 位，且包含字母和数字")
        return value


async def limited(db, action, target):
    count = await db.scalar(
        select(func.count())
        .select_from(Audit)
        .where(Audit.action == action, Audit.target == target, Audit.created_at > now() - timedelta(minutes=10))
    )
    if count >= 10:
        raise HTTPException(429, "尝试次数过多，请 10 分钟后重试")


@router.post("/login")
async def login(body: Login, request: Request):
    peer = request.client.host if request.client else "unknown"
    async with Session.begin() as db:
        await lock(db)
        await limited(db, "login.failed", peer)
        row = await db.scalar(select(AdminCredential).where(AdminCredential.username == body.username))
        if row is None:
            initial = os.environ.get("ADMIN_PASSWORD", "")
            valid = (
                bool(initial)
                and hmac.compare_digest(body.username.encode(), os.getenv("ADMIN_USERNAME", "admin").encode())
                and hmac.compare_digest(body.password.encode(), initial.encode())
            )
            if valid:
                row = AdminCredential(
                    id=uuid.uuid4().hex,
                    username=body.username,
                    password_hash=await asyncio.to_thread(password_hash, initial),
                    auth_version=1,
                )
                db.add(row)
        else:
            candidate = await asyncio.to_thread(password_hash, body.password, row.password_hash.split(":")[0])
            valid = not row.deleted_at and hmac.compare_digest(candidate, row.password_hash)
        db.add(Audit(id=uuid.uuid4().hex, actor="anonymous", action="login.success" if valid else "login.failed", target=peer, detail={}))
        version = row.auth_version if valid else None
    if not valid:
        raise HTTPException(401, "管理员账号或密码不正确")
    return {
        "access_token": jwt.encode(
            {"sub": body.username, "aud": "model-control", "version": version, "exp": now() + timedelta(minutes=30)},
            SECRET,
            algorithm="HS256",
        )
    }


@router.post("/change-password", status_code=204)
async def change_password(body: PasswordChange, request: Request, actor=Depends(admin)):
    token = claims(request)
    failure = None
    async with Session.begin() as db:
        await lock(db)
        await limited(db, "admin.password_failed", actor)
        row = await db.scalar(select(AdminCredential).where(AdminCredential.username == actor))
        if not row or row.deleted_at or row.auth_version != token["version"]:
            raise HTTPException(401, "管理员登录已失效，请重新登录")
        candidate = await asyncio.to_thread(password_hash, body.current_password, row.password_hash.split(":")[0])
        if not hmac.compare_digest(candidate, row.password_hash):
            failure = "原密码不正确"
        elif body.new_password != body.confirmation:
            failure = "两次输入的新密码不一致"
        elif body.new_password == body.current_password:
            failure = "新密码不能与原密码相同"
        if failure:
            db.add(Audit(id=uuid.uuid4().hex, actor=actor, action="admin.password_failed", target=actor, detail={}))
        else:
            row.password_hash = await asyncio.to_thread(password_hash, body.new_password)
            row.auth_version += 1
            db.add(Audit(id=uuid.uuid4().hex, actor=actor, action="admin.password_changed", target=actor, detail={}))
    if failure:
        raise HTTPException(400, failure)
