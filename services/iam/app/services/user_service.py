"""User CRUD, search, activation, and ABAC attribute management."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from app.domain.exceptions import (
    OrganizationNotFoundError,
    PermissionNotFoundError,
    TenantContextRequiredError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)
from app.domain.value_objects import SubjectAttributes, UserStatus
from app.infrastructure.db.models.associations import UserPermissionGrant
from app.infrastructure.db.models.organization import Organization
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.models.user import User
from app.infrastructure.db.repositories.organization_repo import OrganizationRepository
from app.infrastructure.db.repositories.permission_repo import PermissionRepository
from app.infrastructure.db.repositories.user_permission_repo import (
    UserPermissionGrantRepository,
)
from app.infrastructure.db.repositories.user_repo import UserRepository
from sqlalchemy.exc import IntegrityError


def display_username(user: User) -> str:
    """The real `username` column when set, else derived from the email's
    local part — used wherever a username needs to be rendered for an
    account that's never set one (see app.api.v1.routes.users/auth)."""
    return user.username or user.email.split("@", 1)[0]


def account_status(user: User) -> UserStatus:
    """Shared by the login response, GET /users/me, and PATCH .../status —
    just the stored `status` column now (see User.status). UserService.set_status
    is the one place that keeps it in lockstep with `is_active`/`locked_until`,
    so this stays the single source of truth instead of re-deriving it."""
    return cast(UserStatus, user.status)


@dataclass(frozen=True, slots=True)
class ProfileContext:
    """The tenant/role/permissions a user's *current session* is bound to —
    empty when the access token carries no tenant_id claim, or when the
    membership it named has since been revoked (dropped silently, same
    tolerant pattern as AuthService.verify_mfa_and_login)."""

    organization: Organization | None = None
    role: Role | None = None
    permissions: list[str] = field(default_factory=list)


class UserService:
    def __init__(self, session) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._orgs = OrganizationRepository(session)
        self._permissions = PermissionRepository(session)
        self._user_permissions = UserPermissionGrantRepository(session)

    async def get_by_id(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"No user with id '{user_id}'")
        return user

    async def get_profile_context(self, user_id: uuid.UUID, tenant_slug: str | None) -> ProfileContext:
        if tenant_slug is None:
            return ProfileContext()

        organization = await self._orgs.get_by_slug(tenant_slug)
        if organization is None:
            return ProfileContext()

        membership = await self._orgs.get_membership(organization.id, user_id)
        if membership is None:
            return ProfileContext()

        role_codes = {p.code for p in membership.role.permissions}
        direct_grants = await self._user_permissions.list_for_user_in_organization(user_id, organization.id)
        direct_codes = {link.permission.code for link in direct_grants}
        return ProfileContext(
            organization=organization,
            role=membership.role,
            permissions=sorted(role_codes | direct_codes),
        )

    async def get_profile_context_for_user(
        self, user_id: uuid.UUID, tenant_slug: str | None
    ) -> ProfileContext:
        """Resolve tenant/role/permissions for GET /users/{user_id} — unlike
        get_profile_context (driven by the caller's own access-token
        tenant_id claim), there's no session to read a tenant from here, so
        `tenant_slug` is either given explicitly (disambiguates a user who
        belongs to several organizations) or falls back to that user's sole
        organization when they have exactly one. Deliberately never raises
        on ambiguity — this is a profile read, not a login."""
        if tenant_slug is not None:
            return await self.get_profile_context(user_id, tenant_slug)

        organizations = await self._orgs.list_for_user(user_id)
        if len(organizations) != 1:
            return ProfileContext()
        return await self.get_profile_context(user_id, organizations[0].slug)

    async def search(self, query: str | None, *, limit: int = 50, offset: int = 0) -> list[User]:
        if query:
            return await self._users.search(query, limit=limit)
        return await self._users.list_all(limit=limit, offset=offset)

    async def list_for_organization(
        self, organization_id: uuid.UUID, query: str | None, *, limit: int = 50, offset: int = 0
    ) -> list[User]:
        """Tenant-scoped counterpart to `search` — used by GET /users and
        GET /users/search when the caller is an org admin/owner rather than
        a superuser, so they only ever see their own tenant's users."""
        return await self._users.list_for_organization(organization_id, query, limit=limit, offset=offset)

    async def update_profile(
        self,
        user_id: uuid.UUID,
        *,
        full_name: str | None,
        username: str | None = None,
        phone: str | None = None,
        avatar_url: str | None = None,
    ) -> User:
        user = await self.get_by_id(user_id)
        user.full_name = full_name
        user.username = username
        user.phone = phone
        user.avatar_url = avatar_url
        user.updated_at = datetime.now(UTC)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise UsernameAlreadyExistsError(f"Username '{username}' is already taken") from exc
        return user

    async def update_attributes(self, user_id: uuid.UUID, patch: dict) -> User:
        """Merge `patch` into the user's ABAC attribute bag.

        Goes through SubjectAttributes so the same size cap that protects
        the JWT `attrs` claim (see app/domain/value_objects.py) also applies
        here — an admin can't grow a user's attribute bag past what's safe
        to embed in an access token.
        """
        user = await self.get_by_id(user_id)
        merged = SubjectAttributes(user.attributes or {}).merged_with(patch)
        user.attributes = merged.values
        user.updated_at = datetime.now(UTC)
        await self._session.commit()
        return user

    async def set_active(self, user_id: uuid.UUID, *, is_active: bool) -> User:
        """Pre-dates the `status` column (POST /users/{id}/activate|deactivate)
        — kept working as a simple boolean toggle, but routed through
        set_status so the two stay consistent rather than drifting apart."""
        return await self.set_status(user_id, "ACTIVE" if is_active else "INACTIVE")

    async def set_status(self, user_id: uuid.UUID, status: UserStatus) -> User:
        """PATCH /users/{user_id}/status — the one place that changes a
        user's lifecycle `status` and keeps `is_active`/`locked_until` in
        lockstep, so every existing access-gating check in this codebase
        (get_current_user, AuthService) keeps working unmodified off of
        `is_active` alone. Every non-ACTIVE status blocks access
        (`is_active=False`) — there's no "usable but pending" status today.
        """
        user = await self.get_by_id(user_id)
        user.status = status
        user.is_active = status == "ACTIVE"
        if status != "LOCKED":
            user.locked_until = None
            user.failed_login_count = 0
        user.updated_at = datetime.now(UTC)
        await self._session.commit()
        return user

    async def delete(self, user_id: uuid.UUID) -> None:
        user = await self.get_by_id(user_id)
        await self._users.delete(user)
        await self._session.commit()

    # -- direct, org-scoped permission grants ----------------------------
    #
    # Independent of the Role/RolePermission graph — additive only, not
    # currently read by get_member_permissions or PolicyEngineService
    # (see app.infrastructure.db.models.associations.UserPermissionGrant).

    async def _resolve_organization_for_grant(
        self, user_id: uuid.UUID, tenant_slug: str | None
    ) -> Organization:
        """Unlike get_profile_context_for_user (a read, which tolerates
        ambiguity by returning nothing), granting/revoking a permission must
        know exactly which organization to scope it to — ambiguity here is
        an error, not a silent no-op."""
        if tenant_slug is not None:
            organization = await self._orgs.get_by_slug(tenant_slug)
            if organization is None:
                raise OrganizationNotFoundError(f"No tenant '{tenant_slug}'")
            return organization

        organizations = await self._orgs.list_for_user(user_id)
        if len(organizations) != 1:
            raise TenantContextRequiredError(
                "This user belongs to zero or multiple organizations — specify "
                "tenant_id to disambiguate which one to scope this grant to"
            )
        return organizations[0]

    async def _list_direct_permission_codes(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[str]:
        grants = await self._user_permissions.list_for_user_in_organization(user_id, organization_id)
        return sorted(link.permission.code for link in grants)

    async def add_permissions(
        self,
        user_id: uuid.UUID,
        codes: list[str],
        *,
        tenant_slug: str | None,
        granted_by: uuid.UUID,
    ) -> list[str]:
        """POST /users/{user_id}/permissions — idempotent: granting a
        permission the user already directly holds is a no-op, not a
        conflict. Returns the user's full direct-grant set for that
        organization (not just the codes just added)."""
        await self.get_by_id(user_id)
        organization = await self._resolve_organization_for_grant(user_id, tenant_slug)

        now = datetime.now(UTC)
        for code in codes:
            permission = await self._permissions.get_by_code(code)
            if permission is None:
                raise PermissionNotFoundError(f"No permission with code '{code}'")
            existing = await self._user_permissions.get_link(user_id, organization.id, permission.id)
            if existing is None:
                self._user_permissions.add_link(
                    UserPermissionGrant(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        organization_id=organization.id,
                        permission_id=permission.id,
                        granted_by=granted_by,
                        created_at=now,
                    )
                )
        await self._session.commit()
        return await self._list_direct_permission_codes(user_id, organization.id)

    async def remove_permissions(
        self, user_id: uuid.UUID, codes: list[str], *, tenant_slug: str | None
    ) -> None:
        """DELETE /users/{user_id}/permissions — idempotent: removing a
        permission the user doesn't directly hold is a no-op, not an error
        (only an unknown *code* is)."""
        await self.get_by_id(user_id)
        organization = await self._resolve_organization_for_grant(user_id, tenant_slug)

        for code in codes:
            permission = await self._permissions.get_by_code(code)
            if permission is None:
                raise PermissionNotFoundError(f"No permission with code '{code}'")
            link = await self._user_permissions.get_link(user_id, organization.id, permission.id)
            if link is not None:
                await self._user_permissions.remove_link(link)
        await self._session.commit()
