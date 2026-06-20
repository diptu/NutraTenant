# 🔐 IAM Service (RBAC Microservice)

High-performance, production-ready Identity and Access Management service built with FastAPI, utilizing Attribute-Based Access Control (ABAC) and strict architectural separation of concerns.

---

## 🏗️ Separation of Concerns

| Layer | Responsibility |
| :--- | :--- |
| **api** | HTTP delivery layer & endpoint Routing (`FastAPI`) |
| **services** | Orchestrates business logic, domain constraints, and transactions |
| **repositories** | Decoupled data access layer containing raw database queries (`SQLAlchemy`) |
| **models** | Declarative database schemas (`PostgreSQL`) |
| **schemas** | Strict request/response data validation and serialization (`Pydantic v2`) |
| **core** | Low-level security primitives, hashing algorithms, and JWT mechanics |

---

---

## 📂 Layout & Project Structure

```text
services/iam/
├── app/
│   ├── api/v1/
│   │   ├── endpoints/       # Auth, Users, Tenants, Policies, Metrics
│   │   └── middlewares/     # Tenant Context, Dual RBAC-ABAC Interceptors
│   ├── core/                # Config, Cryptography, Security Primitives, OIDC Matrix
│   ├── db/                  # Session factories, SQLAlchemy base setups, migrations
│   ├── engine/              # Policy Decision Point (PDP) & Condition Evaluator DSL
│   ├── models/              # SQLAlchemy multi-tenant domain mapping models
│   ├── schemas/             # Pydantic v2 validation models & evaluation structures
│   ├── repositories/        # Optimized structural database access barriers
│   ├── services/            # Domain orchestration pipelines and business execution
│   └── dependencies/        # Strict FastAPI Dependency Injection guards
└── tests/                   # Matrix-based functional and security pytest suites
```

---

## 🔌 API Matrix (`/api/v1`)

### 🔐 Authentication
* `POST /auth/register` - Registers a unique account. Accepts payload with credential context.
* `POST /auth/login` - Validates keys, issues stateful access/refresh token matrices.
* `POST /auth/refresh` - Evaluates refresh token validity, rotates key states.
* `POST /auth/logout` - Revokes explicit active sessions.

### 👤 User Management
* `GET /users/me` - Retreives contextual state of authorized client.
* `GET /users` | `GET /users/{id}` - Complete and resource-isolated entity lookup (Admin Guarded).
* `PUT /users/{id}` | `DELETE /users/{id}` - Mutation and soft-deletion operations.
* `POST /users/{id}/roles` | `DELETE /users/{id}/roles/{role_id}` - Real-time role inheritance mapping.

### 🧩 Role & Permission Governance
* `POST` | `GET` | `PUT` | `DELETE` `/roles` - Full lifecycle control of system access groups.
* `POST` | `DELETE` `/roles/{id}/permissions` - Aggregates discrete action allowances to specified structural groups.
* `POST` | `GET` | `PUT` | `DELETE` `/permissions` - Fine-grained declarative action boundary specifications.

### 🔎 Authorization & Audit
* `POST /auth/check` - Verifies explicit token authorization state.
* `GET /users/{id}/permissions` | `GET /users/{id}/roles` - Returns evaluated permissions and assigned roles.
* `GET /audit-logs` | `GET /users/{id}/audit-logs` - Context-aware security and operations telemetry extraction.
* `GET /health` - Liveness/Readiness validation probe.


# 🔐 IAM Service API Matrix & Implementation Checklist

## 🔌 API Matrix (`/api/v1`)

---

## 🔑 Tenancy & Authentication

| Method | Endpoint                      | Description                                                                                |
| ------ | ----------------------------- | ------------------------------------------------------------------------------------------ |
| POST   | `/auth/register`              | Registers an identity inside a scoped tenant domain.                                       |
| POST   | `/auth/login`                 | Authenticates user credentials and signs access tokens containing core subject attributes. |
| POST   | `/auth/refresh`               | Validates rotation token vectors and handles single-use token lifecycle shifts.            |
| POST   | `/auth/logout`                | Revokes explicit active sessions and updates invalid token registries.                     |
| GET    | `/auth/oauth/google`          | Computes state/nonce parameters and yields external IDP discovery redirects.               |
| POST   | `/auth/oauth/google/callback` | Consumes OIDC callbacks, validates tokens, and provisions profile parameters.              |

---

## 👥 User Attribute & Profiling

| Method | Endpoint                      | Description                                                                 |
| ------ | ----------------------------- | --------------------------------------------------------------------------- |
| GET    | `/users/me`                   | Retrieves contextual state and dynamic attribute sets of authorized client. |
| GET    | `/users`                      | Scoped tenant identity resolution.                                          |
| GET    | `/users/{id}`                 | Retrieve specific user details (Requires organizational permissions).       |
| PATCH  | `/users/{id}/attributes`      | Mutates fine-grained subject attributes used by policy evaluation.          |
| POST   | `/users/{id}/roles`           | Assign roles to a user.                                                     |
| DELETE | `/users/{id}/roles/{role_id}` | Remove assigned roles from a user.                                          |

---

## 📐 Dynamic Policy & Resource Governance

| Method | Endpoint    |
| ------ | ----------- |
| POST   | `/policies` |
| GET    | `/policies` |
| PUT    | `/policies` |
| DELETE | `/policies` |

**Description:** Complete lifecycle management of dynamic authorization policies.

| Method | Endpoint     |
| ------ | ------------ |
| POST   | `/resources` |
| GET    | `/resources` |
| PATCH  | `/resources` |
| DELETE | `/resources` |

**Description:** Resource registration and classification using runtime attributes.

---

## 🔎 Authorization & Policy Tracing

| Method | Endpoint                 | Description                                                                                    |
| ------ | ------------------------ | ---------------------------------------------------------------------------------------------- |
| POST   | `/auth/evaluate`         | Evaluates Subject, Resource, Action, and Environment access decisions (Policy Decision Point). |
| GET    | `/audit-logs/trace/{id}` | Retrieves detailed policy execution telemetry.                                                 |
| GET    | `/metrics`               | Exposes Prometheus metrics for policy evaluation latency and system performance.               |
| GET    | `/health`                | Readiness and liveness checks for PostgreSQL, Redis, and policy engine components.             |

---

# 📋 Comprehensive Implementation Checklist

## 1. Project Setup

* [ ] Create IAM service repository
* [ ] Configure project structure
* [ ] Setup environment variables

  * JWT signing keys
  * OIDC configuration
  * Tenant settings
* [ ] Configure structured JSON logging
* [ ] Setup database and migrations
* [ ] Configure PostgreSQL GIN indexes
* [ ] Configure testing pipelines
* [ ] Configure CI/CD linting and quality gates

---

## 2. Authentication & Federated Identity

### Registration & Authentication

* [ ] Multi-tenant user registration
* [ ] Tenant-scoped email uniqueness validation
* [ ] Argon2id password hashing
* [ ] JWT access token generation
* [ ] Refresh token rotation
* [ ] Session tracking
* [ ] Login audit logging

### Password Management

* [ ] Password update workflow
* [ ] Forgot-password token generation
* [ ] Password reset validation flow

### OAuth2 / OIDC

* [ ] State and nonce verification
* [ ] OIDC provider discovery
* [ ] Callback processing
* [ ] Identity extraction
* [ ] Local profile provisioning

---

## 3. User Management & Attribute Profiling

* [ ] Tenant-isolated user CRUD
* [ ] User activation/deactivation workflows
* [ ] Profile search and filtering
* [ ] JSONB attribute management

### Example Subject Attributes

```json
{
  "department": "Engineering",
  "clearance": "Level3",
  "cost_center": "CC-100"
}
```

* [ ] Tenant-level schema validation

---

## 4. Tenancy & Resource Configuration

### Tenant Management

* [ ] Organization registration
* [ ] Tenant state validation
* [ ] Tenant lifecycle management

### Resource Classification

* [ ] Resource registration
* [ ] Runtime attribute assignment

Example:

```json
{
  "resource_type": "document",
  "classification": "confidential",
  "region": "APAC",
  "owner_id": "user_123"
}
```

---

## 5. Role Management (RBAC)

### Default Roles

* [ ] Admin
* [ ] Member
* [ ] Guest

### Role Operations

* [ ] Custom role creation
* [ ] Role updates
* [ ] Role assignment
* [ ] Role revocation

---

## 6. ABAC Policy & Rule Management

### Policy Framework

* [ ] Subject attributes
* [ ] Resource attributes
* [ ] Action definitions
* [ ] Environment attributes

### Policy Engine

* [ ] Policy schema design
* [ ] PDP implementation
* [ ] Recursive Boolean evaluation
* [ ] Policy lifecycle management
* [ ] Live policy updates
* [ ] Deny-overrides conflict resolution

---

## 7. Authorization Middleware

### JWT Validation

* [ ] Signature verification
* [ ] Claim validation
* [ ] Tenant validation

### RBAC Layer

* [ ] Role resolution
* [ ] Scope validation

### Environment Context

* [ ] IP Address extraction
* [ ] Timestamp evaluation
* [ ] Geo-location enrichment

### Hybrid Authorization

* [ ] RBAC pre-check
* [ ] ABAC evaluation
* [ ] Unified authorization decision

---

## 8. Audit Logging & Policy Tracing

### Security Events

* [ ] Login tracking
* [ ] Logout tracking
* [ ] Password changes
* [ ] Session modifications

### Policy Audit Trail

* [ ] Policy updates
* [ ] Resource modifications
* [ ] Role changes

### Authorization Tracing

* [ ] Context snapshot storage
* [ ] Rule evaluation history
* [ ] Decision explanation logging

---

## 9. System Security

### Rate Limiting

* [ ] Redis-backed rate limiting
* [ ] API throttling

### Threat Protection

* [ ] Brute-force protection
* [ ] Account lockout mechanisms
* [ ] Token blacklisting
* [ ] Session revocation

### Input Validation

* [ ] SQL Injection prevention
* [ ] NoSQL Injection prevention
* [ ] Payload sanitization
* [ ] Schema validation

---

## 10. Verification Pipelines & Testing

### Unit Tests

* [ ] Authentication services
* [ ] Policy engine
* [ ] RBAC module
* [ ] ABAC module

### Integration Tests

* [ ] Login flow
* [ ] Registration flow
* [ ] OAuth flow
* [ ] Tenant isolation

### Security Testing

* [ ] Permission escalation attempts
* [ ] Token tampering
* [ ] Tenant boundary violations
* [ ] Authorization bypass testing

---

## 11. Production Engineering & Observability

### Health Monitoring

* [ ] Health endpoint
* [ ] Dependency checks
* [ ] Readiness probes
* [ ] Liveness probes

### Metrics

* [ ] Authentication latency
* [ ] Authorization latency
* [ ] Policy evaluation time
* [ ] Database performance
* [ ] Redis performance

### Performance

* [ ] Redis policy caching
* [ ] Query optimization
* [ ] Index tuning
* [ ] Horizontal scalability validation

---

# 🎯 MVP Execution Sequence

## Phase 1 — Core Authentication & Hybrid Foundations

* [ ] Multi-tenant database schema and migrations
* [ ] PostgreSQL JSONB + GIN indexing
* [ ] Registration and login APIs
* [ ] Argon2id password hashing
* [ ] JWT authentication
* [ ] Session management
* [ ] Identity and tenant models
* [ ] Initial RBAC implementation

---

## Phase 2 — ABAC Engine & Operations

* [ ] Deploy OPA or Casbin
* [ ] Build custom PDP service
* [ ] Subject attribute APIs
* [ ] Resource attribute APIs
* [ ] Refresh token rotation
* [ ] Token blacklist service
* [ ] Policy tracing telemetry
* [ ] Audit logging infrastructure

---

## Phase 3 — Enterprise Scale & Advanced Contexts

* [ ] TOTP Multi-Factor Authentication
* [ ] Google OIDC integration
* [ ] Okta OIDC integration
* [ ] Geo-location policy enforcement
* [ ] Time-based authorization controls
* [ ] SCIM synchronization
* [ ] External directory federation
* [ ] Enterprise observability enhancements

---

## 🚀 Recommended Tech Stack

| Component        | Recommendation                    |
| ---------------- | --------------------------------- |
| API Framework    | FastAPI                           |
| Database         | PostgreSQL                        |
| Cache            | Redis                             |
| Policy Engine    | Open Policy Agent (OPA) or Casbin |
| Authentication   | JWT + Refresh Rotation            |
| Password Hashing | Argon2id                          |
| Metrics          | Prometheus                        |
| Dashboards       | Grafana                           |
| Logging          | Structlog + JSON Logs             |
| Background Jobs  | Celery or Dramatiq                |
| Containerization | Docker                            |
| Orchestration    | Kubernetes                        |
| CI/CD            | Azure DevOps                      |

This roadmap delivers a production-grade **Multi-Tenant Hybrid RBAC + ABAC IAM Platform** suitable for SaaS, enterprise authorization, and Zero Trust architectures.
