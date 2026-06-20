"""Idempotent platform RBAC seeding: default global roles + the full
permission catalog, granted entirely to the global `admin` role.

Safe to call repeatedly (on every app startup, or once per test) — every
step checks for an existing row before creating one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.rbac import PLATFORM_PERMISSIONS
from app.infrastructure.db.models.associations import RolePermission
from app.infrastructure.db.models.permission import Permission
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.repositories.permission_repo import PermissionRepository
from app.services.role_service import RoleService


async def seed_rbac_catalog(session) -> tuple[list[Role], list[Permission]]:
    role_service = RoleService(session)
    roles = await role_service.seed_defaults()
    admin_role = next(r for r in roles if r.code == "admin")

    permission_repo = PermissionRepository(session)
    now = datetime.now(UTC)

    permissions: list[Permission] = []
    for code in PLATFORM_PERMISSIONS.values():
        permission = await permission_repo.get_by_code(code)
        if permission is None:
            resource, action = code.split(":", 1)
            permission = Permission(
                id=uuid.uuid4(),
                name=code,
                code=code,
                resource=resource,
                action=action,
                description=None,
                created_at=now,
                updated_at=now,
            )
            permission_repo.add(permission)
            await session.flush()
        permissions.append(permission)

    for permission in permissions:
        link = await permission_repo.get_role_permission(admin_role.id, permission.id)
        if link is None:
            permission_repo.add_role_permission(
                RolePermission(
                    id=uuid.uuid4(),
                    role_id=admin_role.id,
                    permission_id=permission.id,
                    assigned_by=None,
                    created_at=now,
                )
            )

    await session.commit()
    return roles, permissions
