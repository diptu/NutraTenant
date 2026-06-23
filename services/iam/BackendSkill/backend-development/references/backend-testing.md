# Backend Testing Strategies for FastAPI

Comprehensive testing approaches, frameworks, and quality assurance practices for FastAPI microservices (2026).

---

# Test Pyramid (70-20-10 Rule)

```text
        /\
       /E2E\     10% - End-to-End Tests
      /------\
     /Integr.\ 20% - Integration Tests
    /----------\
   /   Unit     \ 70% - Unit Tests
  /--------------\
```

## Rationale

* Unit tests are fast and isolate business logic.
* Integration tests validate API, database, cache, and external service interactions.
* End-to-End tests verify complete user journeys.

---

# Recommended Testing Stack

| Category            | Tool                        |
| ------------------- | --------------------------- |
| Test Runner         | Pytest                      |
| Async Testing       | pytest-asyncio              |
| API Testing         | HTTPX                       |
| Mocking             | pytest-mock / unittest.mock |
| Coverage            | pytest-cov                  |
| Database Containers | Testcontainers              |
| Factory Data        | Factory Boy                 |
| Property Testing    | Hypothesis                  |
| Load Testing        | k6 / Locust                 |
| E2E Testing         | Playwright                  |
| Security Testing    | Bandit, Semgrep, OWASP ZAP  |
| Dependency Scanning | pip-audit, Safety           |

---

# Project Structure

```text
tests/
├── conftest.py
├── unit/
│   ├── services/
│   ├── repositories/
│   └── policies/
├── integration/
│   ├── api/
│   ├── database/
│   └── events/
├── contract/
├── e2e/
├── load/
└── fixtures/
```

---

# Unit Testing

## Service Layer Testing

```python
# tests/unit/services/test_user_service.py

import pytest

async def test_create_user_success(user_service):
    user = await user_service.create_user(
        email="test@example.com",
        password="Password123!"
    )

    assert user.email == "test@example.com"
    assert user.id is not None


async def test_duplicate_email_raises_exception(
    user_service
):
    await user_service.create_user(
        email="test@example.com",
        password="Password123!"
    )

    with pytest.raises(ValueError):
        await user_service.create_user(
            email="test@example.com",
            password="Password123!"
        )
```

## Parametrized Testing

```python
import pytest

@pytest.mark.parametrize(
    "email",
    [
        "",
        "invalid",
        "test@",
        "@example.com",
    ],
)
def test_invalid_email(email):
    with pytest.raises(ValueError):
        validate_email(email)
```

---

# Mocking External Dependencies

```python
from unittest.mock import AsyncMock

async def test_send_welcome_email(
    user_service,
    mocker
):
    mock_send = mocker.patch(
        "app.services.email.EmailService.send_welcome_email",
        new_callable=AsyncMock
    )

    await user_service.create_user(
        email="test@example.com",
        password="Password123!"
    )

    mock_send.assert_called_once()
```

---

# Repository Testing

```python
async def test_save_user(
    user_repository,
    db_session
):
    user = User(
        email="test@example.com"
    )

    await user_repository.create(user)

    await db_session.commit()

    result = await user_repository.get_by_email(
        "test@example.com"
    )

    assert result.email == "test@example.com"
```

---

# FastAPI Integration Testing

## API Endpoint Testing

```python
from httpx import AsyncClient

async def test_create_user(
    async_client: AsyncClient
):
    response = await async_client.post(
        "/api/v1/users",
        json={
            "email": "test@example.com",
            "password": "Password123!"
        }
    )

    assert response.status_code == 201

    data = response.json()

    assert data["email"] == "test@example.com"
```

## Validation Testing

```python
async def test_invalid_email(
    async_client
):
    response = await async_client.post(
        "/api/v1/users",
        json={
            "email": "invalid",
            "password": "Password123!"
        }
    )

    assert response.status_code == 422
```

---

# FastAPI Test Client Fixture

```python
# conftest.py

import pytest
from httpx import AsyncClient

from app.main import app

@pytest.fixture
async def async_client():
    async with AsyncClient(
        app=app,
        base_url="http://test"
    ) as client:
        yield client
```

---

# Database Testing with Testcontainers

## PostgreSQL Container

```python
import pytest

from testcontainers.postgres import (
    PostgresContainer
)

@pytest.fixture(scope="session")
def postgres_container():

    with PostgresContainer(
        "postgres:17"
    ) as postgres:
        yield postgres
```

## SQLAlchemy Connection

```python
@pytest.fixture
async def db_engine(postgres_container):

    engine = create_async_engine(
        postgres_container.get_connection_url()
    )

    yield engine

    await engine.dispose()
```

---

# Testing Alembic Migrations

## Upgrade Validation

```python
def test_upgrade_migration(alembic_runner):

    alembic_runner.migrate_up_to("head")

    inspector = inspect(
        alembic_runner.engine
    )

    columns = [
        col["name"]
        for col in inspector.get_columns("users")
    ]

    assert "email" in columns
```

## Downgrade Validation

```python
def test_downgrade_migration(
    alembic_runner
):
    alembic_runner.migrate_up_to("head")
    alembic_runner.migrate_down_one()

    current = alembic_runner.current()

    assert current != "head"
```

---

# Multi-Tenant SaaS Testing

## Tenant Isolation

```python
async def test_tenant_data_isolation(
    async_client,
    tenant_a_token,
    tenant_b_token
):
    response = await async_client.get(
        "/api/v1/users",
        headers={
            "Authorization":
            f"Bearer {tenant_a_token}"
        }
    )

    users = response.json()

    assert all(
        user["tenant_id"] ==
        TENANT_A_ID
        for user in users
    )
```

---

# ABAC Authorization Testing

## Policy Evaluation

```python
async def test_abac_policy():

    decision = await policy_engine.evaluate(
        subject={
            "role": "manager"
        },
        resource={
            "owner": "department-a"
        },
        action="read"
    )

    assert decision.allowed is True
```

## Authorization Endpoint

```python
async def test_authorize_endpoint(
    async_client
):
    response = await async_client.post(
        "/authorize",
        json={
            "subject": {
                "role": "admin"
            },
            "action": "delete",
            "resource": {
                "owner": "tenant-1"
            }
        }
    )

    assert response.status_code == 200
```

---

# Event-Driven Testing

## Kafka Event Publication

```python
async def test_user_created_event(
    kafka_producer,
    user_service
):
    await user_service.create_user(
        email="test@example.com",
        password="Password123!"
    )

    event = kafka_producer.last_message()

    assert event.topic == "user.created"
```

---

# Contract Testing

## OpenAPI Contract Validation

```python
def test_openapi_schema():

    schema = app.openapi()

    assert "/api/v1/users" in schema["paths"]

    assert (
        "UserResponse"
        in schema["components"]["schemas"]
    )
```

## Consumer-Driven Contracts

Tools:

* Pact Python
* OpenAPI Diff
* Schemathesis

```bash
schemathesis run \
  http://localhost:8000/openapi.json
```

---

# Load Testing

## k6

```javascript
import http from "k6/http";

export default function () {
    http.get(
        "http://localhost:8000/health"
    );
}
```

## Locust

```python
from locust import HttpUser, task

class ApiUser(HttpUser):

    @task
    def users(self):
        self.client.get("/api/v1/users")
```

## Performance Targets

| Metric       | Target     |
| ------------ | ---------- |
| P95          | < 500ms    |
| P99          | < 1s       |
| Error Rate   | < 1%       |
| Availability | > 99.9%    |
| Throughput   | SLA Driven |

---

# End-to-End Testing

## Playwright

```python
from playwright.sync_api import sync_playwright

def test_login_flow():

    with sync_playwright() as p:

        browser = p.chromium.launch()

        page = browser.new_page()

        page.goto(
            "http://localhost:3000/login"
        )

        page.fill(
            "#email",
            "test@example.com"
        )

        page.fill(
            "#password",
            "Password123!"
        )

        page.click("button[type=submit]")

        assert "/dashboard" in page.url

        browser.close()
```

---

# Security Testing

## Bandit

```bash
bandit -r app/
```

## Semgrep

```bash
semgrep --config auto app/
```

## Dependency Scanning

```bash
pip-audit

safety check
```

## OWASP ZAP

```bash
docker run \
  -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py \
  -t http://localhost:8000
```

---

# Coverage

## Coverage Goals

| Area             | Target |
| ---------------- | ------ |
| Overall          | 80%+   |
| Services         | 90%+   |
| Authorization    | 100%   |
| Authentication   | 100%   |
| Tenant Isolation | 100%   |
| Policy Engine    | 100%   |

## Run Coverage

```bash
pytest \
  --cov=app \
  --cov-report=html \
  --cov-report=term
```

---

# GitHub Actions CI/CD

```yaml
name: FastAPI Test Pipeline

on:
  pull_request:
  push:

jobs:
  tests:

    runs-on: ubuntu-latest

    services:

      postgres:
        image: postgres:17

        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: test_db

        ports:
          - 5432:5432

    steps:

      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6

      - name: Install dependencies
        run: uv sync

      - name: Run linting
        run: ruff check .

      - name: Run formatting check
        run: ruff format --check .

      - name: Run type checking
        run: mypy app/

      - name: Run tests
        run: pytest

      - name: Coverage
        run: |
          pytest \
            --cov=app \
            --cov-report=xml

      - name: Security Scan
        run: |
          bandit -r app/
          pip-audit
```

---

# Testing Best Practices

1. Follow Arrange → Act → Assert.
2. Test business logic separately from API routes.
3. Mock external systems only.
4. Use real PostgreSQL for integration tests.
5. Avoid SQLite for production-like testing.
6. Ensure tenant isolation is fully covered.
7. Test authorization policies independently.
8. Keep unit tests under 50ms.
9. Run integration tests in CI.
10. Make tests deterministic and parallelizable.

---

# Testing Checklist

## Unit

* [ ] Service tests
* [ ] Repository tests
* [ ] Policy engine tests
* [ ] Utility tests

## Integration

* [ ] API endpoint tests
* [ ] Database tests
* [ ] Redis tests
* [ ] Event tests

## Security

* [ ] Authentication tests
* [ ] Authorization tests
* [ ] Tenant isolation tests
* [ ] OWASP scans

## Quality

* [ ] Coverage > 80%
* [ ] CI/CD automation
* [ ] Migration validation
* [ ] OpenAPI contract validation

## SaaS-Specific

* [ ] Tenant isolation
* [ ] Role-based access control
* [ ] Attribute-based access control
* [ ] Audit logging validation
* [ ] Invitation workflow testing
* [ ] Subscription enforcement testing
* [ ] Policy engine validation
* [ ] Cross-tenant attack prevention

---

# Recommended Pytest Plugins

```bash
uv add --dev \
    pytest \
    pytest-asyncio \
    pytest-cov \
    pytest-mock \
    pytest-xdist \
    factory-boy \
    testcontainers \
    hypothesis
```

---

# Resources

* FastAPI Documentation
* Pytest Documentation
* Testcontainers Python
* Schemathesis
* Playwright Python
* Locust
* k6
* Bandit
* Semgrep
* OWASP ZAP
