"""Group.type/status and GroupMembership.membership_type/role/status
(migration 0022) — backing the Groups & Group Memberships API."""

from __future__ import annotations

from typing import Literal

GroupType = Literal["SYSTEM", "CUSTOM"]
GroupStatus = Literal["ACTIVE", "INACTIVE"]
GroupMembershipType = Literal["DIRECT", "INHERITED"]
GroupMembershipRole = Literal["MEMBER", "ADMIN", "OWNER"]
GroupMembershipStatus = Literal["ACTIVE", "INACTIVE", "EXPIRED"]
