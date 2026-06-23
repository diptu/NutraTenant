from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.modules.auth.models import RefreshToken
from app.modules.auth.repositories.interfaces.token_repository import RefreshTokenRepository
from app.modules.auth.schemas.dto.token_pair_dto import TokenPair
from app.modules.auth.utils.jwt import create_access_token, create_refresh_token
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization
    from app.modules.users.models import User


async def issue_token_pair(
    session: AsyncSession,
    settings: Settings,
    refresh_tokens: RefreshTokenRepository,
    user: User,
    *,
    family_id: uuid.UUID,
    ip_address: str | None,
    user_agent: str | None,
    rotates: RefreshToken | None = None,
    organization: Organization | None = None,
) -> TokenPair:
    new_jti = uuid.uuid4()
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(days=settings.refresh_token_expire_days)

    new_row = RefreshToken(
        id=new_jti,
        user_id=user.id,
        family_id=family_id,
        issued_at=issued_at,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
        organization_id=organization.id if organization else None,
    )
    refresh_tokens.add(new_row)
    # Flush the INSERT before the UPDATE below: replaced_by_jti is a
    # self-referential FK on this same table, and SQLAlchemy's unit-of-
    # work only topologically sorts same-flush operations using declared
    # relationships, not raw FK columns — so in one flush it can (and on
    # Postgres, did) emit the UPDATE before the new row's INSERT,
    # violating fk_refresh_tokens_replaced_by_jti_refresh_tokens.
    await session.flush()

    if rotates is not None:
        rotates.revoked_at = datetime.now(UTC)
        rotates.replaced_by_jti = new_jti
        await session.flush()

    # session_id == this RefreshToken row's id: org/role context is
    # resolved dynamically from it per-request (see
    # app.modules.auth.dependencies.get_current_tenant_slug) rather than
    # embedded directly, so it can't go stale within one access token's
    # lifetime if role/membership changes mid-session.
    access_token = create_access_token(
        settings,
        user_id=user.id,
        session_id=new_jti,
        attributes=user.attributes,
        is_superuser=user.is_superuser,
    )
    access_expires_at = issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    refresh_token_str = create_refresh_token(
        settings,
        user_id=user.id,
        jti=new_jti,
        family_id=family_id,
        expires_at=expires_at,
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token_str,
        session_id=new_jti,
        issued_at=issued_at,
        expires_at=access_expires_at,
    )


async def issue_new_session(
    session: AsyncSession,
    settings: Settings,
    refresh_tokens: RefreshTokenRepository,
    user: User,
    *,
    ip_address: str | None,
    user_agent: str | None,
    organization: Organization | None = None,
) -> TokenPair:
    """Start a brand-new rotation family — used by password login, the
    post-MFA verify step, and the Google OIDC callback once an identity
    has been resolved to a user. ``organization`` is omitted by the
    Google flow today (it has no tenant-resolution step yet)."""
    return await issue_token_pair(
        session,
        settings,
        refresh_tokens,
        user,
        family_id=uuid.uuid4(),
        ip_address=ip_address,
        user_agent=user_agent,
        organization=organization,
    )
