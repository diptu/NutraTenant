"""Import every model so they register on Base.metadata (Alembic + test schema creation)."""

from app.infrastructure.db.models.associations import (
    RolePermission,
    UserOrganizationRole,
)
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.organization import Organization
from app.infrastructure.db.models.organization_invitation import (
    OrganizationInvitation,
)
from app.infrastructure.db.models.password_reset_token import PasswordResetToken
from app.infrastructure.db.models.permission import Permission
from app.infrastructure.db.models.policy import Policy
from app.infrastructure.db.models.policy_evaluation_log import PolicyEvaluationLog
from app.infrastructure.db.models.refresh_token import RefreshToken
from app.infrastructure.db.models.resource import Resource
from app.infrastructure.db.models.role import Role
from app.infrastructure.db.models.user import User
from app.infrastructure.db.models.user_role import UserRole

__all__ = [
    "AuditLog",
    "Organization",
    "OrganizationInvitation",
    "PasswordResetToken",
    "Permission",
    "Policy",
    "PolicyEvaluationLog",
    "RefreshToken",
    "Resource",
    "Role",
    "RolePermission",
    "User",
    "UserOrganizationRole",
    "UserRole",
]
