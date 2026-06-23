"""Import every model so they register on Base.metadata (Alembic + test
schema creation). Every domain owns its own `models.py`; this module just
aggregates them plus the cross-module association tables."""

from app.audit import AuditLog
from app.infrastructure.database.associations import (
    OrganizationTenant,
    RolePermission,
    UserOrganizationRole,
    UserPermissionGrant,
)
from app.modules.access_governance.models import AccessApproval, AccessRequest, AccessReview
from app.modules.auth.models import EmailVerificationToken, PasswordResetToken, RefreshToken
from app.modules.groups.models import Group, GroupMembership
from app.modules.organizations.models import Organization, OrganizationInvitation
from app.modules.permissions.models import Permission
from app.modules.policies.models import Policy, PolicyEvaluationLog
from app.modules.reserved_tenant_ids.models import ReservedTenantId
from app.modules.resources.models import Resource
from app.modules.roles.models import Role, UserRole
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

__all__ = [
    "AccessApproval",
    "AccessRequest",
    "AccessReview",
    "AuditLog",
    "EmailVerificationToken",
    "Group",
    "GroupMembership",
    "Organization",
    "OrganizationInvitation",
    "OrganizationTenant",
    "PasswordResetToken",
    "Permission",
    "Policy",
    "PolicyEvaluationLog",
    "RefreshToken",
    "ReservedTenantId",
    "Resource",
    "Role",
    "RolePermission",
    "Tenant",
    "User",
    "UserOrganizationRole",
    "UserPermissionGrant",
    "UserRole",
]
