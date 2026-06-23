---
name: fastapi
description: |
  Build Python APIs with FastAPI, Pydantic v2, and SQLAlchemy 2.0. Covers project structure,
  async patterns, JWT authentication, validation, and database integration with uv package manager.

  Use when: creating Python APIs, setting up FastAPI projects, implementing JWT auth, configuring
  SQLAlchemy async, or troubleshooting 422 validation errors, CORS issues, or async blocking.
---

# FastAPI Skill

Production-tested patterns for FastAPI with Pydantic v2, SQLAlchemy 2.0 async, and JWT authentication.

**Latest Versions** (verified December 2025):
- FastAPI: 0.137.2
- pydantic-settings: 2.14.2
- SQLAlchemy: 2.0.30
- Uvicorn: 0.35.0
- pyjwt:2.13.0

---

## Quick Start

# Project Structure (Enterprise FastAPI)

For enterprise applications, especially IAM, SaaS, Multi-Tenant platforms, organize code by domain and architectural layers.

## Architecture Flow

```text
HTTP Request
      ↓
API Route (v1/v2)
      ↓
Request Schema
      ↓
Use Case
      ↓
Service Layer
      ↓
Repository Layer
      ↓
SQLAlchemy Model
      ↓
Database

Response DTO
      ↑
API Response
```

## Recommended Structure

```text
app/
│
├── main.py
├── lifespan.py
│
├── api/
│   │
│   ├── v1/
│   │   │
│   │   ├── router.py
│   │   │
│   │   ├── auth/
│   │   │   ├── routes.py
│   │   │   ├── requests.py
│   │   │   └── responses.py
│   │   │
│   │   ├── users/
│   │   │   ├── routes.py
│   │   │   ├── requests.py
│   │   │   └── responses.py
│   │   │
│   │   ├── tenants/
│   │   ├── organizations/
│   │   ├── memberships/
│   │   ├── roles/
│   │   ├── permissions/
│   │   ├── policies/
│   │   └── authorization/
│   │
│   └── v2/
│
├── modules/
│
│   ├── auth/
│   │
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── session.py
│   │   │   └── refresh_token.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── commands/
│   │   │   ├── queries/
│   │   │   └── dto/
│   │   │
│   │   ├── repositories/
│   │   │   ├── interfaces/
│   │   │   └── sqlalchemy/
│   │   │
│   │   ├── services/
│   │   │
│   │   ├── use_cases/
│   │   │
│   │   └── events/
│   │
│   ├── users/
│   ├── tenants/
│   ├── organizations/
│   ├── memberships/
│   ├── roles/
│   ├── permissions/
│   ├── policies/
│   ├── authorization/
│   ├── sessions/
│   ├── api_keys/
│   ├── invitations/
│   ├── mfa/
│   ├── audit_logs/
│   ├── notifications/
│   ├── webhooks/
│   └── sso/
│
├── infrastructure/
│   │
│   ├── database/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── migrations/
│   │
│   ├── cache/
│   ├── email/
│   ├── messaging/
│   ├── storage/
│   └── identity_providers/
│
├── shared/
│   │
│   ├── dependencies/
│   ├── exceptions/
│   ├── enums/
│   ├── constants/
│   ├── security/
│   ├── pagination/
│   └── utils/
│
└── tests/
```

## Layer Responsibilities

### API Layer

Location:

```text
api/v1/*
api/v2/*
```

Responsibilities:

* HTTP handling
* Request validation
* Response serialization
* OpenAPI documentation
* Authentication dependencies

Never place business logic here.

### Request / Response Layer

Location:

```text
api/v1/users/requests.py
api/v1/users/responses.py
```

Responsibilities:

* Public API contracts
* Swagger documentation
* Version-specific payloads

Example:

```python
class CreateUserRequest(BaseModel):
    email: EmailStr
    first_name: str
```

### Command Layer

Location:

```text
modules/users/schemas/commands/
```

Responsibilities:

* Internal write operations

Example:

```python
class CreateUserCommand(BaseModel):
    email: str
    first_name: str
```

### Query Layer

Location:

```text
modules/users/schemas/queries/
```

Responsibilities:

* Read requests
* Filtering
* Search criteria

Example:

```python
class ListUsersQuery(BaseModel):
    page: int
    page_size: int
```

### DTO Layer

Location:

```text
modules/users/schemas/dto/
```

Responsibilities:

* Data transfer between layers

Example:

```python
class UserDTO(BaseModel):
    id: UUID
    email: str
    first_name: str
```

### Model Layer

Location:

```text
modules/users/models/
```

Responsibilities:

* SQLAlchemy ORM models
* Relationships
* Constraints
* Indexes

Example:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID]
    email: Mapped[str]
```

Never place business logic in models.

### Repository Layer

Location:

```text
modules/users/repositories/
```

Responsibilities:

* Database access
* CRUD operations
* Query execution

Example:

```python
class UserRepository:

    async def get_by_email(
        self,
        email: str
    ) -> User | None:
        ...
```

Repository must not contain business rules.

### Service Layer

Location:

```text
modules/users/services/
```

Responsibilities:

* Business rules
* Domain validation
* Domain policies

Example:

```python
class UserService:

    async def create_user(
        self,
        command: CreateUserCommand
    ) -> UserDTO:
        ...
```

### Use Case Layer

Location:

```text
modules/users/use_cases/
```

Responsibilities:

* Application workflows
* Service orchestration
* Transaction boundaries

Example:

```python
class CreateUserUseCase:

    async def execute(
        self,
        command: CreateUserCommand
    ):
        ...
```

### Infrastructure Layer

Location:

```text
infrastructure/
```

Responsibilities:

* PostgreSQL
* Redis
* Kafka
* RabbitMQ
* Azure Storage
* Email providers
* SSO integrations

No business logic should live here.

## Dependency Injection

Centralize dependency wiring.

```text
shared/dependencies/
├── repositories.py
├── services.py
└── use_cases.py
```

Example:

```python
def get_user_repository():
    return SQLAlchemyUserRepository()

def get_user_service(
    repository: UserRepository,
):
    return UserService(repository)
```

## API Versioning

Version only the API layer.

Correct:

```text
api/
├── v1/
└── v2/
```

Avoid:

```text
modules/
├── users_v1/
├── users_v2/
```

Business logic should be shared across API versions whenever possible.

## Recommended Domains for IAM

```text
auth
users
tenants
organizations
memberships
roles
permissions
policies
authorization
sessions
api_keys
audit_logs
invitations
mfa
notifications
webhooks
sso
```

This architecture scales from a single FastAPI service to a large enterprise IAM platform with hundreds of endpoints and multiple development teams.
