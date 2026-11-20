from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta, timezone
from typing import Annotated

import jwt
from anyio import CapacityLimiter, to_thread
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


async def password_work(function, *args):
    return await to_thread.run_sync(function, *args, limiter=_password_limit)


_password_limit = CapacityLimiter(4)
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


def _encode_access(user: UserModel, family_id: str) -> tuple[str, int]:
    now = utcnow()
    expires = now + timedelta(minutes=settings.access_token_minutes)
    token = jwt.encode(
        {"sub": user.id, "sid": family_id, "username": user.username, "role": user.role, "ver": user.auth_version, "type": "access", "iat": now, "exp": expires},
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


async def issue_tokens(user: UserModel, request: Request, response: Response, session: AsyncSession, family_id: str | None = None) -> dict:
    raw_refresh = secrets.token_urlsafe(48)
    now = utcnow()
    family_id = family_id or uuid.uuid4().hex
    roles, permissions = await load_admin_access(session, user)
    session.add(
        RefreshTokenModel(
            id=f"refresh-{uuid.uuid4().hex}",
            user_id=user.id,
            token_hash=_token_hash(raw_refresh),
            family_id=family_id,
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
    access, expires_in = _encode_access(user, family_id)
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
        if payload.get("type") != "access" or not payload.get("sid"):
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
    active_session = await session.scalar(
        select(RefreshTokenModel.id)
        .where(
            RefreshTokenModel.user_id == user_id,
            RefreshTokenModel.family_id == payload.get("sid"),
            RefreshTokenModel.revoked_at.is_(None),
            RefreshTokenModel.deleted_at.is_(None),
            RefreshTokenModel.expires_at > utcnow(),
        )
        .limit(1)
    )
    if not active_session:
        raise HTTPException(401, "登录会话已失效", headers={"WWW-Authenticate": "Bearer"})
    if user.must_change_password and request.url.path not in {
        "/api/auth/me",
        "/api/auth/change-password",
        "/api/auth/logout",
    }:
        raise HTTPException(403, "首次登录必须先修改密码")
    from .model_gateway import set_owner

    set_owner(user.id)
    request.state.user_id = user.id
    request.state.access_expiry = payload["exp"]
    request.state.auth_version = token_version
    request.state.session_family = payload["sid"]
    await attach_admin_access(session, user)
    from .agent_attribution import current_agent_attribution

    if current_agent_attribution()[0] == "agent_test" and settings.app_env == "production":
        if not is_super_admin(user) and user.username not in settings.agent_test_usernames:
            raise HTTPException(403, "当前账号未获授权执行 Agent 开发测试")
    return user


CurrentUser = Annotated[UserModel, Depends(require_user)]


async def login(username: str, password: str, session: AsyncSession) -> UserModel | None:
    user = await session.scalar(select(UserModel).where(UserModel.username == username.strip().lower(), UserModel.deleted_at.is_(None)).with_for_update())
    if not user or user.status != "active" or not await password_work(verify_password, user.password_hash, password):
        return None
    user.last_login_at = utcnow()
    return user


async def stream_session_active(request: Request, user_id: str) -> bool:
    if utcnow().timestamp() >= request.state.access_expiry:
        return False
    async with session_factory() as session:
        return bool(
            await session.scalar(
                select(RefreshTokenModel.id)
                .join(UserModel, UserModel.id == RefreshTokenModel.user_id)
                .where(
                    RefreshTokenModel.user_id == user_id,
                    RefreshTokenModel.family_id == request.state.session_family,
                    RefreshTokenModel.deleted_at.is_(None),
                    RefreshTokenModel.revoked_at.is_(None),
                    RefreshTokenModel.expires_at > utcnow(),
                    UserModel.deleted_at.is_(None),
                    UserModel.status == "active",
                    UserModel.auth_version == request.state.auth_version,
                )
                .limit(1)
            )
        )


async def _locked_refresh(session: AsyncSession, raw_token: str) -> tuple[UserModel | None, RefreshTokenModel | None]:
    # 同一账号的轮换和退出按用户行串行；拿锁后再读凭证，才能看到并发轮换的后继记录。
    token_hash = _token_hash(raw_token)
    owner = select(RefreshTokenModel.user_id).where(RefreshTokenModel.token_hash == token_hash).scalar_subquery()
    user = await session.scalar(select(UserModel).where(UserModel.id == owner).with_for_update())
    token = await session.scalar(select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash))
    return user, token


async def _revoke_family(session: AsyncSession, token: RefreshTokenModel) -> None:
    now = utcnow()
    await session.execute(
        update(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == token.user_id,
            (RefreshTokenModel.family_id == (token.family_id or token.id)) | (RefreshTokenModel.id == token.id),
            RefreshTokenModel.deleted_at.is_(None),
        )
        .values(revoked_at=now, deleted_at=now, updated_at=now)
    )


async def rotate_refresh(raw_token: str | None, request: Request, response: Response, session: AsyncSession) -> dict | None:
    if not raw_token:
        return None
    user, token = await _locked_refresh(session, raw_token)
    now = utcnow()
    if not token or not user or user.deleted_at or user.status != "active" or token.expires_at.replace(tzinfo=timezone.utc) <= now:
        return None
    revoked = token.revoked_at or token.deleted_at
    if revoked:
        if (now - revoked.replace(tzinfo=timezone.utc)).total_seconds() >= 5:
            await _revoke_family(session, token)
            await session.commit()
        return None
    token.family_id = token.family_id or token.id
    token.revoked_at = token.deleted_at = now
    return await issue_tokens(user, request, response, session, token.family_id)


LogoutCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


async def revoke_refresh(raw_token: str | None, credentials: HTTPAuthorizationCredentials | None) -> None:
    async with session_factory() as session:
        if raw_token:
            _, token = await _locked_refresh(session, raw_token)
            if token:
                await _revoke_family(session, token)
                await session.commit()
                return
        if credentials:
            try:
                payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
            except jwt.PyJWTError:
                return
            if payload.get("type") == "access" and payload.get("sid"):
                await session.scalar(select(UserModel.id).where(UserModel.id == payload["sub"]).with_for_update())
                token = await session.scalar(select(RefreshTokenModel).where(RefreshTokenModel.user_id == payload["sub"], RefreshTokenModel.family_id == payload["sid"]).limit(1))
                if token:
                    await _revoke_family(session, token)
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


async def refresh_cookie_value(value: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None) -> str | None:
    return value


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
