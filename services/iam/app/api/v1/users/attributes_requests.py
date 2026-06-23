"""Request bodies for GET/PUT /api/v1/user-attributes/{user_id}
(User Domain API Specification) — a thin facade over the same ABAC
attribute bag PATCH /users/{user_id}/attributes already manages."""

from __future__ import annotations

from pydantic import BaseModel


class UpdateUserAttributesRequest(BaseModel):
    """A bare attribute patch — every key in the body is merged into the
    user's existing attribute bag (see UserService.update_attributes), not
    a `{"attributes": {...}}` envelope."""

    model_config = {"extra": "allow"}
