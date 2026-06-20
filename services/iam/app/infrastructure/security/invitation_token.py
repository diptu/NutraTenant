"""Organization invitation tokens — only the sha256 hash is ever persisted.

Same shape as app.infrastructure.security.reset_token (sha256 hex digest is
exactly 64 characters, matching ``organization_invitations.token_hash``),
kept as its own module so the invitation and password-reset token
namespaces can't collide and each can evolve its own TTL independently.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_invitation_token() -> tuple[str, str]:
    """Returns ``(raw_token, token_hash)`` — persist only the hash; the raw
    value goes to the caller (an email link, in a real deployment)."""
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_invitation_token(raw_token)


def hash_invitation_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
