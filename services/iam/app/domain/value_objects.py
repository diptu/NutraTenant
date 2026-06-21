"""Framework-free value objects — no SQLAlchemy/FastAPI/pydantic imports here."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_ATTRIBUTE_BYTES = 8 * 1024  # keeps the JSONB column small and the JWT it can feed cheap

# User.status (migration 0017) — the admin-settable account lifecycle label
# backing PATCH /users/{id}/status. Shared by the API schema (request/
# response validation) and the service layer (UserService.set_status),
# hence living here rather than in either of those modules.
UserStatus = Literal["ACTIVE", "INACTIVE", "SUSPENDED", "LOCKED", "PENDING_VERIFICATION", "DELETED"]


@dataclass(frozen=True, slots=True)
class Email:
    """A validated, normalized (lowercased + stripped) email address."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise ValueError(f"'{self.value}' is not a valid email address")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SubjectAttributes:
    """The dynamic ABAC attribute bag stored on ``users.attributes`` (JSONB).

    Deliberately a flat ``dict[str, Any]`` rather than a fixed schema — each
    tenant may define its own attribute keys (``department``, ``clearance``,
    ``region``, ``cost_center``, ...). Validation here is limited to keeping
    the bag small and JSON-safe; per-tenant key/value schema enforcement is
    out of scope for this value object.
    """

    values: dict[str, Any]

    def __post_init__(self) -> None:
        for key in self.values:
            if not isinstance(key, str) or not key:
                raise ValueError("attribute keys must be non-empty strings")
        if len(json.dumps(self.values)) > _MAX_ATTRIBUTE_BYTES:
            raise ValueError(f"attribute bag exceeds {_MAX_ATTRIBUTE_BYTES} bytes")

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def merged_with(self, patch: dict[str, Any]) -> SubjectAttributes:
        return SubjectAttributes({**self.values, **patch})
