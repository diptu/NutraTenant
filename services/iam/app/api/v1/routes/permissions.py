"""Permission catalog endpoints — out of scope for this milestone (auth + federation).

Wired into app/main.py as an empty router so the app boots; populate as the
RBAC/ABAC policy engine is built out.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/permissions", tags=["permissions"])
