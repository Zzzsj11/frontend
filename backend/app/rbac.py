from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AdminPermissionModel, AdminRoleModel, AdminRolePermissionModel, UserAdminRoleModel, UserModel

SUPER_ADMIN_ROLE = "super_admin"
ASS_ADMIN_ROLE = "ass_admin"
SONG_EMOTIONS_READ = "song_emotions.read"
SONG_EMOTIONS_MANAGE = "song_emotions.manage"


async def load_admin_access(db: AsyncSession, user: UserModel) -> tuple[list[str], list[str]]:
    if user.role != "admin":
        return [], []
    role_codes = list(
        (
            await db.execute(
                select(AdminRoleModel.code)
                .join(UserAdminRoleModel, UserAdminRoleModel.role_id == AdminRoleModel.id)
                .where(
                    UserAdminRoleModel.user_id == user.id,
                    UserAdminRoleModel.deleted_at.is_(None),
                    AdminRoleModel.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    permissions = list(
        (
            await db.execute(
                select(AdminPermissionModel.code)
                .join(AdminRolePermissionModel, AdminRolePermissionModel.permission_id == AdminPermissionModel.id)
                .join(UserAdminRoleModel, UserAdminRoleModel.role_id == AdminRolePermissionModel.role_id)
                .where(
                    UserAdminRoleModel.user_id == user.id,
                    UserAdminRoleModel.deleted_at.is_(None),
                    AdminRolePermissionModel.deleted_at.is_(None),
                    AdminPermissionModel.deleted_at.is_(None),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return sorted(role_codes), sorted(permissions)


async def attach_admin_access(db: AsyncSession, user: UserModel) -> None:
    roles, permissions = await load_admin_access(db, user)
    user.admin_role_codes = roles
    user.admin_permissions = permissions


def is_super_admin(user: UserModel) -> bool:
    return user.role == "admin" and SUPER_ADMIN_ROLE in getattr(user, "admin_role_codes", [])


def require_super_admin(user: UserModel) -> None:
    if not is_super_admin(user):
        raise HTTPException(403, "需要超级管理员权限")


def require_permission(user: UserModel, permission: str) -> None:
    if is_super_admin(user):
        return
    if user.role != "admin" or permission not in getattr(user, "admin_permissions", []):
        raise HTTPException(403, "无此后台功能权限")
