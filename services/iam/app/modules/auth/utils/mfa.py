"""TOTP-based MFA: secret encryption at rest, code/recovery-code verification.

Uses ``pyotp`` for RFC 6238 TOTP generation/verification, and Fernet
(symmetric encryption, already pulled in via ``cryptography`` for Google's
JWKS verification — see app.modules.auth.utils.oauth) to encrypt the TOTP secret at
rest: unlike a password, it can't be one-way hashed, since verifying a code
needs the original secret back.
"""

from __future__ import annotations

import hashlib
import secrets

import pyotp
from app.core.config import Settings
from app.modules.auth.exceptions import InvalidTokenError
from cryptography.fernet import Fernet, InvalidToken

_ISSUER = "NutraTenant"
# Excludes 0/O/1/I — ambiguous when a user transcribes a recovery code by hand.
_RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_RECOVERY_CODE_LENGTH = 10


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_otpauth_uri(*, secret: str, account_email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=account_email, issuer_name=_ISSUER)


def verify_totp_code(secret: str, code: str) -> bool:
    """``valid_window=1`` tolerates one 30s step of clock drift either way."""
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def encrypt_secret(settings: Settings, secret: str) -> str:
    return Fernet(settings.mfa_secret_encryption_key).encrypt(secret.encode()).decode()


def decrypt_secret(settings: Settings, encrypted_secret: str) -> str:
    try:
        return Fernet(settings.mfa_secret_encryption_key).decrypt(encrypted_secret.encode()).decode()
    except InvalidToken as exc:
        raise InvalidTokenError("MFA secret could not be decrypted") from exc


def generate_recovery_codes(count: int) -> list[str]:
    """Returns ``count`` raw recovery codes — persist only their hashes
    (see ``hash_recovery_code``); the raw values are shown to the user once."""
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_CODE_ALPHABET) for _ in range(_RECOVERY_CODE_LENGTH))
        half = _RECOVERY_CODE_LENGTH // 2
        codes.append(f"{raw[:half]}-{raw[half:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    normalized = code.replace("-", "").strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
