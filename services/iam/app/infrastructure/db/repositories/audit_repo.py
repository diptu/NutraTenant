"""Audit log repository — append-only, no update/delete operations exposed."""

from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.repositories.base_repository import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    """Persistence access for :class:`AuditLog`."""

    model = AuditLog
