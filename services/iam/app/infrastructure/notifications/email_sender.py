"""Stub transactional email delivery — no real provider wired up yet.

Same situation as password-reset and org-invitation tokens elsewhere in this
service: there's no $0-stack email/notification provider, so the "send"
just logs and returns. Swap the body for a real provider (SES/SendGrid/
Postmark, ...) without touching call sites — the signatures here are the
intended integration seam.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def send_invite_email(*, to: str, temp_password: str, tenant_name: str) -> None:
    """Admin-provisioning welcome email carrying a temp password.

    The temp password is deliberately never logged — only its existence is,
    even in this stub. A real provider's call goes here.
    """
    logger.info(
        "STUB email: invite for %s to join '%s' (temp password omitted from logs)",
        to,
        tenant_name,
    )


async def send_tenant_invite_email(*, to: str, invite_token: str, tenant_name: str) -> None:
    """Tenant-bootstrap welcome email carrying an invite link/token (as
    opposed to a temp password — see send_invite_email above)."""
    logger.info(
        "STUB email: tenant '%s' bootstrap invite for %s (token omitted from logs)",
        tenant_name,
        to,
    )
