import pytest
from app.api.v1.dependencies import get_async_db, reset_oidc_client
from app.core.cache import (
    InMemoryPermissionCache,
    get_permission_cache,
    reset_permission_cache,
)
from app.core.rate_limit import (
    InMemoryRateLimiter,
    get_rate_limiter,
    reset_rate_limiter,
)
from app.core.token_blacklist import (
    InMemoryTokenBlacklist,
    get_token_blacklist,
    reset_token_blacklist,
)
from app.infrastructure.db import (
    models as _models,  # noqa: F401 - registers every model on Base.metadata
)
from app.infrastructure.db.base import Base
from app.main import app as app_instance
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend():
    """Forces pytest-anyio to use the asyncio backend."""
    return "asyncio"


@pytest.fixture
async def test_db():
    """
    Function-scoped database fixture. Provides a completely pristine
    database environment for every single test.
    """
    # StaticPool keeps exactly one underlying DBAPI connection alive for the
    # engine's whole lifetime, and hands that *same* connection out to every
    # checkout — the documented SQLAlchemy pattern for sharing a SQLite
    # `:memory:` database across multiple sessions (see "Using a Memory
    # Database in Multiple Threads" in the SQLAlchemy SQLite dialect docs).
    # The previous approach (`?cache=shared` + the default connection pool)
    # relied on SQLite's shared-cache reference counting across *separate*
    # physical connections — correct only as long as at least one of them
    # stays open at all times. That's timing-sensitive: on a CI runner with
    # different I/O/thread scheduling than a local machine, a connection
    # could close (returning it to "no connections reference this shared
    # cache" state, which destroys the in-memory DB) in the gap between one
    # test's teardown and the next test's setup, surfacing as an
    # intermittent "no such table: users" — reproducible on GitHub Actions
    # but not necessarily locally. StaticPool removes the ambiguity by
    # never having more than one connection in the first place.
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield testing_session_local

    await engine.dispose()


@pytest.fixture
def app(test_db):
    """Overrides the fastAPI dependency injection per-test."""

    async def _override_get_db():
        async with test_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Override get_async_db (the dependency the router actually declares via Depends)
    # rather than get_db, which is called directly inside get_async_db and thus
    # bypasses FastAPI's dependency_overrides lookup.
    app_instance.dependency_overrides[get_async_db] = _override_get_db

    # Override with a fresh in-memory limiter per test: one instance shared
    # across every request *within* this test (so exhaustion/backoff
    # behavior is testable), but never the real Redis-backed singleton —
    # there's no Redis server in the test environment, and unlike a
    # construction-time failure (which get_rate_limiter() already handles),
    # a real client would only fail once something tries to actually use it.
    test_rate_limiter = InMemoryRateLimiter()
    app_instance.dependency_overrides[get_rate_limiter] = lambda: test_rate_limiter
    reset_rate_limiter()

    # Same reasoning as the rate limiter above — get_current_user (and
    # AuthService.logout/change_password/reset_password) go through this on
    # every request, and there's no Redis server here.
    test_token_blacklist = InMemoryTokenBlacklist()
    app_instance.dependency_overrides[get_token_blacklist] = lambda: test_token_blacklist
    reset_token_blacklist()

    # Same again — OrganizationService resolves member permissions through
    # this for the role-grant escalation guard.
    test_permission_cache = InMemoryPermissionCache()
    app_instance.dependency_overrides[get_permission_cache] = lambda: test_permission_cache
    reset_permission_cache()

    # get_oidc_client is a process-wide singleton (so its JWKS cache
    # survives across *production* requests) — reset it so one test's
    # mocked JWKS/respx routes can never leak into another test via a
    # stale cached client.
    reset_oidc_client()

    yield app_instance

    app_instance.dependency_overrides.clear()
    reset_rate_limiter()
    reset_permission_cache()
    reset_token_blacklist()
    reset_oidc_client()


@pytest.fixture
async def client(app):
    """Provides an isolated HTTPX Client to individual test instances."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session(test_db):
    """
    Raw async session for test-level data seeding (e.g. inserting expired tokens).
    Uses the same in-memory SQLite instance as the app, via the same
    StaticPool-backed engine (see test_db).
    """
    async with test_db() as session:
        yield session
