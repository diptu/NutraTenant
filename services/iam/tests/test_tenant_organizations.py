"""Unit tests for the new Tenant entity and its many-to-many link to
Organization (see app/services/tenant_service.py).

This Tenant is additive and currently has no HTTP surface: the pre-existing
"tenant" vocabulary used by the API (Organization.slug, the `tenant_id`
claim on access tokens, /login, /users/me, /switch-tenant, /tenants
bootstrap) is unchanged. These are pure service-level tests against the raw
`db_session` fixture rather than the HTTP layer, accordingly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.domain.exceptions import (
    OrganizationNotFoundError,
    OrganizationTenantLinkAlreadyExistsError,
    OrganizationTenantLinkNotFoundError,
    TenantAlreadyExistsError,
    TenantNotFoundError,
)
from app.infrastructure.db.models.organization import Organization
from app.infrastructure.db.models.user import User
from app.services.organization_service import OrganizationService
from app.services.tenant_service import TenantService

pytestmark = pytest.mark.anyio


async def _make_user(db_session, email: str) -> User:
    now = datetime.now(UTC)
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name=None,
        password_hash="irrelevant-test-hash",
        attributes={},
        is_active=True,
        is_verified=False,
        is_superuser=False,
        failed_login_count=0,
        created_at=now,
        updated_at=now,
        password_changed_at=now,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _make_organization(db_session, *, name: str, slug: str) -> Organization:
    owner = await _make_user(db_session, f"{slug}-owner@test.com")
    return await OrganizationService(db_session).create(
        name=name, slug=slug, description=None, owner_id=owner.id
    )


@pytest.fixture
def tenant_service(db_session) -> TenantService:
    return TenantService(db_session)


class TestTenantLifecycle:
    async def test_create_and_get(self, tenant_service):
        tenant = await tenant_service.create(name="Acme Group", slug="acme-group")
        assert tenant.is_active is True

        fetched = await tenant_service.get(tenant.id)
        assert fetched.id == tenant.id

        by_slug = await tenant_service.get_by_slug("acme-group")
        assert by_slug.id == tenant.id

    async def test_duplicate_slug_rejected(self, tenant_service):
        await tenant_service.create(name="Acme Group", slug="dupe-slug")
        with pytest.raises(TenantAlreadyExistsError):
            await tenant_service.create(name="Different Name", slug="dupe-slug")

    async def test_get_missing_raises_not_found(self, tenant_service):
        with pytest.raises(TenantNotFoundError):
            await tenant_service.get(uuid.uuid4())
        with pytest.raises(TenantNotFoundError):
            await tenant_service.get_by_slug("does-not-exist")

    async def test_update(self, tenant_service):
        tenant = await tenant_service.create(name="Old Name", slug="update-me")
        updated = await tenant_service.update(tenant.id, name="New Name", is_active=False)
        assert updated.name == "New Name"
        assert updated.is_active is False

    async def test_delete_removes_tenant_and_its_links(self, tenant_service, db_session):
        tenant = await tenant_service.create(name="Doomed", slug="doomed-tenant")
        org = await _make_organization(db_session, name="Org A", slug="org-a-doomed")
        await tenant_service.link_organization(tenant.id, org.id)

        await tenant_service.delete(tenant.id)

        with pytest.raises(TenantNotFoundError):
            await tenant_service.get(tenant.id)


class TestOrganizationTenantMembership:
    async def test_organization_can_join_multiple_tenants(self, tenant_service, db_session):
        org = await _make_organization(db_session, name="Multi Org", slug="multi-org")
        tenant_a = await tenant_service.create(name="Tenant A", slug="tenant-a")
        tenant_b = await tenant_service.create(name="Tenant B", slug="tenant-b")

        await tenant_service.link_organization(tenant_a.id, org.id)
        await tenant_service.link_organization(tenant_b.id, org.id)

        tenants = await tenant_service.list_tenants_for_organization(org.id)
        assert {t.id for t in tenants} == {tenant_a.id, tenant_b.id}

    async def test_tenant_can_have_multiple_organizations(self, tenant_service, db_session):
        tenant = await tenant_service.create(name="Shared Tenant", slug="shared-tenant")
        org_a = await _make_organization(db_session, name="Org A", slug="shared-org-a")
        org_b = await _make_organization(db_session, name="Org B", slug="shared-org-b")

        await tenant_service.link_organization(tenant.id, org_a.id)
        await tenant_service.link_organization(tenant.id, org_b.id)

        organizations = await tenant_service.list_organizations(tenant.id)
        assert {o.id for o in organizations} == {org_a.id, org_b.id}

    async def test_link_unknown_tenant_raises_not_found(self, tenant_service, db_session):
        org = await _make_organization(db_session, name="Org", slug="org-unknown-tenant")
        with pytest.raises(TenantNotFoundError):
            await tenant_service.link_organization(uuid.uuid4(), org.id)

    async def test_link_unknown_organization_raises_not_found(self, tenant_service):
        tenant = await tenant_service.create(name="Tenant", slug="tenant-unknown-org")
        with pytest.raises(OrganizationNotFoundError):
            await tenant_service.link_organization(tenant.id, uuid.uuid4())

    async def test_duplicate_link_rejected(self, tenant_service, db_session):
        tenant = await tenant_service.create(name="Tenant", slug="tenant-dupe-link")
        org = await _make_organization(db_session, name="Org", slug="org-dupe-link")
        await tenant_service.link_organization(tenant.id, org.id)
        with pytest.raises(OrganizationTenantLinkAlreadyExistsError):
            await tenant_service.link_organization(tenant.id, org.id)

    async def test_unlink_removes_link(self, tenant_service, db_session):
        tenant = await tenant_service.create(name="Tenant", slug="tenant-unlink")
        org = await _make_organization(db_session, name="Org", slug="org-unlink")
        await tenant_service.link_organization(tenant.id, org.id)

        await tenant_service.unlink_organization(tenant.id, org.id)

        assert await tenant_service.list_organizations(tenant.id) == []

    async def test_unlink_missing_link_raises_not_found(self, tenant_service, db_session):
        tenant = await tenant_service.create(name="Tenant", slug="tenant-no-link")
        org = await _make_organization(db_session, name="Org", slug="org-no-link")
        with pytest.raises(OrganizationTenantLinkNotFoundError):
            await tenant_service.unlink_organization(tenant.id, org.id)


class TestOrganizationDeletionWithTenantLinks:
    async def test_deleting_organization_cleans_up_tenant_links(self, tenant_service, db_session):
        tenant = await tenant_service.create(name="Tenant", slug="tenant-org-delete")
        org = await _make_organization(db_session, name="Org", slug="org-to-delete")
        await tenant_service.link_organization(tenant.id, org.id)

        await OrganizationService(db_session).delete(org.id)

        # The tenant itself survives; only its link to the deleted org is gone.
        assert await tenant_service.get(tenant.id) is not None
        assert await tenant_service.list_organizations(tenant.id) == []
