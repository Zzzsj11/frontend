from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import database_session, session_factory
from .models import RefreshTokenModel, UserModel, utcnow
from .rbac import attach_admin_access, is_super_admin, load_admin_access

password_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)
REFRESH_COOKIE = "mv_refresh_token"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _encode_access(user: UserModel) -> tuple[str, int]:
    now = utcnow()
    expires = now + timedelta(minutes=settings.access_token_minutes)
    token = jwt.encode(
        {"sub": user.id, "username": user.username, "role": user.role, "ver": user.auth_version, "type": "access", "iat": now, "exp": expires},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return token, settings.access_token_minutes * 60


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def user_public(user: UserModel) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "role": user.role,
        "mustChangePassword": user.must_change_password,
        "dailyChatLimit": user.daily_chat_limit,
        "dailyImageLimit": user.daily_image_limit,
        "dailyVideoLimit": user.daily_video_limit,
        "adminRoleCodes": getattr(user, "admin_role_codes", []),
        "permissions": getattr(user, "admin_permissions", []),
        "isSuperAdmin": is_super_admin(user),
    }


async def issue_tokens(user: UserModel, request: Request, response: Response) -> dict:
    raw_refresh = secrets.token_urlsafe(48)
    now = utcnow()
    async with session_factory() as session:
        roles, permissions = await load_admin_access(session, user)
        session.add(
            RefreshTokenModel(
                id=f"refresh-{uuid.uuid4().hex}",
                user_id=user.id,
                token_hash=_token_hash(raw_refresh),
                expires_at=now + timedelta(days=settings.refresh_token_days),
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
            )
        )
        await session.commit()
    user.admin_role_codes = roles
    user.admin_permissions = permissions
    response.set_cookie(
        REFRESH_COOKIE,
        raw_refresh,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )
    access, expires_in = _encode_access(user)
    return {"accessToken": access, "expiresIn": expires_in, "user": user_public(user)}


async def require_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(database_session)],
) -> UserModel:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "未登录", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise ValueError
        user_id = str(payload["sub"])
        token_version = int(payload.get("ver", 0))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(401, "登录已过期", headers={"WWW-Authenticate": "Bearer"}) from exc
    user = await session.get(UserModel, user_id)
    if not user or user.deleted_at is not None or user.status != "active":
        raise HTTPException(401, "用户不可用")
    if token_version != user.auth_version:
        raise HTTPException(401, "登录凭证已失效", headers={"WWW-Authenticate": "Bearer"})
    if user.must_change_password and request.url.path not in {
        "/api/auth/me",
        "/api/auth/change-password",
        "/api/auth/logout",
    }:
        raise HTTPException(403, "首次登录必须先修改密码")
    request.state.user_id = user.id
    await attach_admin_access(session, user)
    return user


CurrentUser = Annotated[UserModel, Depends(require_user)]


async def login(username: str, password: str) -> UserModel | None:
    async with session_factory() as session:
        result = await session.execute(select(UserModel).where(UserModel.username == username.strip().lower(), UserModel.deleted_at.is_(None)))
        user = result.scalar_one_or_none()
        if not user or user.status != "active" or not verify_password(user.password_hash, password):
            return None
        user.last_login_at = utcnow()
        await session.commit()
        return user


async def rotate_refresh(raw_token: str | None) -> UserModel | None:
    if not raw_token:
        return None
    now = utcnow()
    async with session_factory() as session:
        result = await session.execute(
            select(RefreshTokenModel).where(
                RefreshTokenModel.token_hash == _token_hash(raw_token),
                RefreshTokenModel.deleted_at.is_(None),
                RefreshTokenModel.revoked_at.is_(None),
                RefreshTokenModel.expires_at > now,
            )
        )
        token = result.scalar_one_or_none()
        if not token:
            return None
        token.revoked_at = now
        token.deleted_at = now
        user = await session.get(UserModel, token.user_id)
        await session.commit()
        if not user or user.deleted_at is not None or user.status != "active":
            return None
        return user


async def revoke_refresh(raw_token: str | None) -> None:
    if not raw_token:
        return
    now = utcnow()
    async with session_factory() as session:
        result = await session.execute(select(RefreshTokenModel).where(RefreshTokenModel.token_hash == _token_hash(raw_token), RefreshTokenModel.deleted_at.is_(None)))
        token = result.scalar_one_or_none()
        if token:
            token.revoked_at = now
            token.deleted_at = now
            await session.commit()


async def revoke_all_refresh_tokens(user_id: str, session: AsyncSession) -> None:
    now = utcnow()
    await session.execute(
        update(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == user_id,
            RefreshTokenModel.deleted_at.is_(None),
            RefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, deleted_at=now, updated_at=now)
    )


async def seed_admin() -> None:
    async with session_factory() as session:
        current = (await session.execute(select(UserModel).where(UserModel.username == "admin"))).scalar_one_or_none()
        if current:
            return
        legacy = (await session.execute(select(UserModel).where(UserModel.username == "admin01"))).scalar_one_or_none()
        if legacy:
            legacy.username = "admin"
            await session.commit()
            return
        session.add(
            UserModel(
                id=f"user-{uuid.uuid4().hex}",
                username="admin",
                display_name="管理员",
                password_hash=hash_password("123456"),
                role="admin",
                must_change_password=True,
            )
        )
        await session.commit()


async def refresh_cookie_value(value: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None) -> str | None:
    return value


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
