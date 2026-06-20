# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Service purpose

The IAM service is NutraTenant's Tenant & Identity microservice: multi-tenant auth (registration, login, JWT access/refresh, Google OIDC) plus hybrid RBAC + ABAC authorization (roles → permissions, with an attribute-based Policy Decision Point as the longer-term target). It is one service inside the NutraTenant monorepo — see the repo-root `CLAUDE.md` for cross-service conventions (per-service DB, Outbox/Circuit-Breaker/tracing requirements, etc.). Everything below is specific to `services/iam`.

`ABAC_IAM_checklist.md` (in this directory) is the authoritative phased RBAC/ABAC checklist for this service. `docs/checklist.md` is an earlier/overlapping draft of the same checklist — when the two disagree, treat `ABAC_IAM_checklist.md` as current and flag the conflict rather than silently reconciling it.

## Current state — mid-migration, app does not currently boot

This service is actively being restructured from a flatter layout (`app/models`, `app/db`, `app/audit`, `app/middleware`, `app/core/security.py`, `app/repositories/`, `app/schemas/`) into a DDD-style layout (`app/domain`, `app/infrastructure`, `app/services`, `app/api/v1`). The migration is **incomplete**:

- `app/core/config.py`, `app/core/logging.py`, `app/core/security_headers.py`, `app/domain/exceptions.py`, and `app/domain/value_objects.py` are all currently empty (0 bytes), even though `app/main.py` imports `get_settings`, `configure_logging`, `SecurityHeadersMiddleware`, and the `DomainError` subclasses from them.
- `app/infrastructure/db/base.py` and `app/api/v1/dependencies.py` do not exist on disk at all, despite being imported by `app/main.py` / `tests/conftest.py`. (Their compiled `.pyc` files are still sitting in `__pycache__/`, confirming they had real content before being emptied/removed.)
- `app/api/v1/routes/`, `app/api/v1/schemas/`, `app/services/`, `app/infrastructure/db/models/`, and `app/infrastructure/security/` exist as directories but are currently empty — no model classes (`User`, `Role`, `Organization`, `Permission`, `AuditLog`, association tables) exist yet at their new `app/infrastructure/db/models/` location, even though the repositories in `app/infrastructure/db/repositories/` already import from there.
- The entire `tests/` suite (`test_auth.py`, `test_rbac_tenancy.py`, `test_user_management.py`, etc.) still imports from the **old** pre-migration paths (`app.models.user`, `app.db.base`, `app.db.seed_rbac`, `app.audit.logger`, `app.core.security`, `app.core.rbac`, `app.middleware.authorization`, `app.repositories.user`, `app.schemas.user`) — none of which exist in the current tree. The suite will not collect against the current `app/` layout.

Practical implication: don't assume `uv run pytest`, `uv run uvicorn app.main:app`, or any import of `app.main` currently succeeds — check the relevant module exists and is non-empty before relying on it. The most up-to-date, intact code is the repository layer (`app/infrastructure/db/repositories/*.py`); treat `app/domain/*` and the missing `app/infrastructure/db/{base,models}` as the next things that need to be (re)written before the service runs.

## Commands

Run from `services/iam/` unless noted. This service uses `uv` (Python 3.11.9, pinned via `.python-version`).

```bash
# Install/sync dependencies (deps + dev group: pytest, ruff, mypy)
uv sync --all-groups

# Run the dev server (matches the Dockerfile.service CMD)
uv run uvicorn app.main:app --reload --port 8000

# Tests — whole suite, a single file, or a single test
uv run pytest -q
uv run pytest tests/test_auth.py
uv run pytest tests/test_auth.py::test_login_returns_tokens -q

# Lint / format / typecheck
uv run ruff check .
uv run ruff check --fix .
uv run ruff format .
uv run mypy --explicit-package-bases .

# Alembic migrations (DATABASE_URL comes from app/core/config settings, not alembic.ini)
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic revision --autogenerate -m "add x column"
uv run alembic current
```

From the **repo root**, the `Taskfile.yml` wraps the same commands per-service (defaults to all services in `SERVICES` if `SERVICE` is omitted):

```bash
task test:one SERVICE=iam          # uv run pytest for iam only
task lint SERVICE=iam              # ruff check
task typecheck SERVICE=iam         # mypy --explicit-package-bases
task format SERVICE=iam            # ruff check --fix + ruff format
task quality SERVICE=iam           # format -> lint -> typecheck -> test, in order
task migrate SERVICE=iam           # alembic upgrade head
task migrate:revision SERVICE=iam MESSAGE="..."
task ci-local:one SERVICE=iam      # mirrors CI: uv sync --all-groups, ruff check, pytest -q
task docker:up SERVICE=iam         # docker compose build+run just the iam container
```

Note: `Taskfile.yml`'s `ci-local`/`ci-emulate` tasks describe themselves as mirroring `.github/workflows/ci.yml`, but no `.github/workflows/` directory currently exists in the repo — there is no CI pipeline to actually mirror yet.

## Architecture (target layout)

Per `README.md`, the intended separation of concerns once the migration above is finished:

| Layer | Location | Responsibility |
|---|---|---|
| `api` | `app/api/v1/routes`, `app/api/v1/schemas` | FastAPI routing + Pydantic v2 request/response models |
| `services` | `app/services` | Business-logic orchestration, transactions, domain-rule enforcement |
| `domain` | `app/domain` | Framework-free entities, value objects, and `DomainError` subclasses (no SQLAlchemy/FastAPI imports) |
| `infrastructure` | `app/infrastructure/db/{models,repositories}`, `app/infrastructure/security` | SQLAlchemy models, repositories, JWT/crypto primitives |
| `core` | `app/core` | Settings (`get_settings()`), structured logging setup, security headers middleware |

Conventions visible in the repository layer (the most intact part of the codebase right now), worth following when filling in the rest:

- Every repository subclasses the generic `BaseRepository[ModelT]` (`app/infrastructure/db/repositories/base_repository.py`) for `get_by_id`/`list_all`/`add`/`delete`, and adds only its own query methods (`get_by_email`, `get_by_slug`, `get_with_permissions`, ...).
- Relationships are declared `lazy="raise"` on the ORM models, so any code path that needs related data must eager-load explicitly via `selectinload` chains (see `UserRepository.get_with_org_roles`) — a silent N+1 lazy-load is a bug, not a convenience, in this codebase.
- `app/main.py` centralizes domain → HTTP status mapping in a single `DomainError` exception handler: `AccountLockedError` → 423 + `Retry-After` header, `InvalidCredentialsError`/`InvalidTokenError` → 401, `*NotFoundError` → 404, `EmailAlreadyExistsError` → 409, everything else → 400. New domain exceptions should be added to the `_NOT_FOUND_ERRORS`/`_UNAUTHORIZED_ERRORS` tuples there rather than getting their own per-route try/except unless the status code is a one-off.
- Multi-tenancy is modeled as `Organization` ←(`UserOrganizationRole`)→ `User`, and `Role` ←(`RolePermission`)→ `Permission` — i.e. roles are scoped per-organization-membership, not global to a user.

## Database

- Async SQLAlchemy + `asyncpg`, PostgreSQL (Neon-compatible connection strings). Local Postgres runs on port `5433` (see `infrastructure/docker-compose.yml` / `.env.example`) specifically to avoid colliding with a system Postgres on `5432`.
- Migrations live in `alembic/versions/`; `alembic/env.py` reads `DATABASE_URL` from the app settings object rather than from `alembic.ini` (`sqlalchemy.url` is intentionally left blank there).
- Tests use an in-memory SQLite engine with `StaticPool` (`tests/conftest.py`) — one shared connection for the engine's whole lifetime, specifically to avoid an intermittent "no such table" failure that the previous shared-cache-without-StaticPool setup hit on CI but not locally.
