"""Application settings — single source of truth for env-driven configuration.

Values are read from the process environment / ``.env`` (see ``.env.example``
for the full var list and defaults used in local development).
"""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "nutratenant-identity-service"
    environment: str = "development"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/nutratenant_identity"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "change-me-to-a-long-random-value"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    password_reset_token_expire_minutes: int = 30
    email_verification_token_expire_minutes: int = 15
    # 24h (86,400s) — the explicit TTL requirement for tenant invitations.
    organization_invitation_expire_minutes: int = 24 * 60

    mfa_challenge_token_expire_minutes: int = 5
    mfa_recovery_code_count: int = 8
    # Fernet key encrypting TOTP secrets at rest (unlike a password, a TOTP
    # secret can't be one-way hashed — verification needs the original
    # value back). Dev-only default; override in any real deployment.
    mfa_secret_encryption_key: str = "JsaKd0V4JCvvLuGZU7JCfzV559YLSa-uGe6hfgCTajg="

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    google_oauth_state_ttl_seconds: int = 600

    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Per-tenant subdomain frontends (e.g. apple-corp.localhost:3000) don't
    # match any single fixed origin above — CORSMiddleware's allow_origins
    # is an exact-string list, with no subdomain wildcarding. Each entry
    # here ("localhost:3000", later a real base domain) becomes a regex
    # alternative matching that bare host:port *and* any "{tenant}." prefix
    # of it, via `cors_origin_regex()` below.
    cors_allowed_base_domains: list[str] = Field(default_factory=lambda: ["localhost:3000"])

    def cors_origin_regex(self) -> str | None:
        """Built from `cors_allowed_base_domains` — passed to CORSMiddleware's
        `allow_origin_regex` alongside the static `cors_allow_origins` list
        (Starlette checks an incoming Origin against both; either matching
        is enough)."""
        if not self.cors_allowed_base_domains:
            return None
        alternatives = "|".join(re.escape(domain) for domain in self.cors_allowed_base_domains)
        return rf"^https?://([a-z0-9-]+\.)?({alternatives})$"

    rate_limit_window_seconds: int = 60
    rate_limit_max_requests: int = 60

    lockout_max_attempts: int = 5
    lockout_base_seconds: int = 30
    lockout_max_seconds: int = 3600

    # Comma-separated CIDR blocks treated as "the corporate network" for the
    # `context.ip_in_corporate_range` ABAC attribute (e.g. policies like
    # "Allow if Context.IP within CorporateRange"). Empty = nothing matches.
    corporate_ip_cidrs: list[str] = Field(default_factory=list)

    # Gates Strict-Transport-Security (see app/core/security_headers.py).
    # False only for plain-http local dev — HSTS on a non-HTTPS origin just
    # breaks the next request, it doesn't add any protection.
    cookie_secure: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
