"""Aggregates every module's router under a single `/api/v1` mount point."""

from __future__ import annotations

from app.api.v1.access_governance import routes as access_governance
from app.api.v1.access_governance import summary_routes as access
from app.api.v1.auth import routes as auth
from app.api.v1.groups import membership_routes as group_memberships
from app.api.v1.groups import routes as groups
from app.api.v1.groups import user_group_routes as user_groups
from app.api.v1.organizations import bootstrap_routes as tenants
from app.api.v1.organizations import routes as organizations
from app.api.v1.permissions import routes as permissions
from app.api.v1.policies import routes as policies
from app.api.v1.reserved_tenant_ids import routes as reserved_tenant_ids
from app.api.v1.resources import routes as resources
from app.api.v1.roles import routes as roles
from app.api.v1.routes import admin
from app.api.v1.tenants import routes as tenant_groups
from app.api.v1.users import attributes_routes, profile_routes, status_routes
from app.api.v1.users import routes as users
from fastapi import APIRouter

router = APIRouter()

router.include_router(auth.router)
router.include_router(users.router)
router.include_router(organizations.router)
router.include_router(reserved_tenant_ids.router)
router.include_router(roles.router)
router.include_router(permissions.router)
router.include_router(resources.router)
router.include_router(policies.router)
router.include_router(tenants.router)
router.include_router(tenant_groups.router)
router.include_router(groups.router)
router.include_router(group_memberships.router)
router.include_router(attributes_routes.router)
router.include_router(user_groups.router)
router.include_router(profile_routes.router)
router.include_router(status_routes.router)
router.include_router(access.router)
router.include_router(access_governance.access_requests_router)
router.include_router(access_governance.access_reviews_router)
router.include_router(access_governance.access_approvals_router)
router.include_router(admin.router)
