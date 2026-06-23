"""One-off CLI to provision (or promote) a platform superuser directly in
the DB — bypasses the HTTP registration flow since there's no existing
superuser yet to call POST /admin/users with.

Usage: uv run python scripts/create_superuser.py <email> <password> [full_name]
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime

from app.infrastructure.database.session import async_session_factory, engine
from app.modules.auth.utils.passwords import hash_password
from app.modules.users.models import User
from app.modules.users.repositories.sqlalchemy.user_repository import UserRepository
from app.shared.value_objects import Email


async def main(email: str, password: str, full_name: str | None) -> None:
    normalized_email = Email(email).value
    async with async_session_factory() as session:
        users = UserRepository(session)
        existing = await users.get_by_email(normalized_email)
        if existing is not None:
            existing.is_superuser = True
            existing.is_active = True
            existing.password_hash = hash_password(password)
            existing.updated_at = datetime.now(UTC)
            session.add(existing)
            await session.commit()
            print(f"Promoted existing user {normalized_email} to superuser.")
            return

        now = datetime.now(UTC)
        user = User(
            id=uuid.uuid4(),
            email=normalized_email,
            full_name=full_name,
            password_hash=hash_password(password),
            attributes={},
            is_active=True,
            is_verified=True,
            is_superuser=True,
            failed_login_count=0,
            created_at=now,
            updated_at=now,
            password_changed_at=now,
        )
        users.add(user)
        await session.commit()
        print(f"Created superuser {normalized_email} ({user.id}).")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
