from __future__ import annotations

import uuid

from app.domain.exceptions import TenantContextRequiredError
from app.modules.organizations.exceptions import OrganizationNotFoundError
from app.modules.organizations.models import Organization
from app.modules.organizations.repositories.interfaces.organization_repository import (
    OrganizationRepository,
)
from app.modules.users.repositories.interfaces.user_repository import (
    UserPermissionGrantRepository,
)


async def resolve_organization_for_grant(
    orgs: OrganizationRepository, user_id: uuid.UUID, tenant_slug: str | None
) -> Organization:
    """Unlike get_profile_context_for_user (a read, which tolerates
    ambiguity by returning nothing), granting/revoking a permission must
    know exactly which organization to scope it to — ambiguity here is
    an error, not a silent no-op."""
    if tenant_slug is not None:
        organization = await orgs.get_by_slug(tenant_slug)
        if organization is None:
            raise OrganizationNotFoundError(f"No tenant '{tenant_slug}'")
        return organization

    organizations = await orgs.list_for_user(user_id)
    if len(organizations) != 1:
        raise TenantContextRequiredError(
            "This user belongs to zero or multiple organizations — specify "
            "tenant_id to disambiguate which one to scope this grant to"
        )
    return organizations[0]


async def list_direct_permission_codes(
    user_permissions: UserPermissionGrantRepository, user_id: uuid.UUID, organization_id: uuid.UUID
) -> list[str]:
    grants = await user_permissions.list_for_user_in_organization(user_id, organization_id)
    return sorted(link.permission.code for link in grants)
