"""FastAPI dependency providers for domains not yet migrated into their own
per-domain `dependencies.py` (see app/auth/dependencies.py for the first
one) — shrinks as each remaining domain migrates, until this file is deleted.
"""

from __future__ import annotations

# Re-exported for routes that haven't been migrated to import these directly
# from app.modules.auth.dependencies yet.
from app.modules.auth.dependencies import (
    get_async_db,
    get_auth_service,
    get_current_access_claims,
    get_current_tenant_slug,
    get_current_user,
    get_google_oauth_service,
    get_oidc_client,
    get_state_store,
    get_token_cache,
    require_global_role,
    require_superuser,
)
from app.modules.organizations.dependencies import get_organization_service
from app.modules.reserved_tenant_ids.dependencies import get_reserved_tenant_id_service
from app.modules.resources.dependencies import get_resource_service
from app.modules.users.dependencies import get_user_service

__all__ = [
    "get_async_db",
    "get_auth_service",
    "get_current_access_claims",
    "get_current_tenant_slug",
    "get_current_user",
    "get_google_oauth_service",
    "get_oidc_client",
    "get_organization_service",
    "get_reserved_tenant_id_service",
    "get_resource_service",
    "get_state_store",
    "get_token_cache",
    "get_user_service",
    "require_global_role",
    "require_superuser",
]


