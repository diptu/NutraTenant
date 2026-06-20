"""Password reset tokens — only the sha256 hash is ever persisted.

sha256's hex digest is exactly 64 characters, matching
``password_reset_tokens.token_hash`` (migration 0001) precisely.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_reset_token() -> tuple[str, str]:
    """Returns ``(raw_token, token_hash)`` — persist only the hash; the raw
    value goes to the caller (an email link, in a real deployment)."""
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_reset_token(raw_token)


def hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
