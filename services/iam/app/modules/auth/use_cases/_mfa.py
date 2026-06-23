from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.modules.auth.utils.mfa import decrypt_secret, hash_recovery_code, verify_totp_code

if TYPE_CHECKING:
    from app.modules.users.models import User


async def consume_mfa_code(settings: Settings, user: User, code: str) -> bool:
    """Tries the code as a live TOTP code first, then as a one-time
    recovery code (consuming it on success)."""
    assert user.mfa_secret_encrypted is not None
    secret = decrypt_secret(settings, user.mfa_secret_encrypted)
    if verify_totp_code(secret, code):
        return True

    code_hash = hash_recovery_code(code)
    if code_hash in user.mfa_recovery_codes:
        user.mfa_recovery_codes = [stored for stored in user.mfa_recovery_codes if stored != code_hash]
        user.updated_at = datetime.now(UTC)
        return True

    return False
