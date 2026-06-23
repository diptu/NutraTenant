# HOW-TO-X.md

Implementation Playbooks for NutraTenant

Enterprise Multi-Tenant IAM + ABAC Platform

Built With:

* FastAPI
* Pydantic v2
* SQLAlchemy 2.0
* PostgreSQL
* Redis
* OpenTelemetry
* JWT Authentication
* RBAC + ABAC Authorization
* Repository Pattern
* Service Layer
* Use Cases
* Event-Driven Architecture

---

# Architecture Principles

NutraTenant follows:

```text
API Layer
    ↓
Use Cases
    ↓
Services
    ↓
Repositories
    ↓
Database
```

Authorization is handled through:

```text
PEP (Enforcement)
        ↓
PDP (Policy Engine)
        ↓
RBAC
        +
ABAC
```

Business logic NEVER belongs in routes.

Authorization NEVER belongs in routes.

---

# Module Structure

```text
modules/

├── auth/
├── users/
├── organizations/
├── tenants/
├── memberships/
├── roles/
├── permissions/
├── policies/
├── authorization/
├── sessions/
├── mfa/
├── api_keys/
├── service_accounts/
├── audit_logs/
├── notifications/
└── observability/
```

Every module follows:

```text
module/

├── models/
├── schemas/
│   ├── commands/
│   ├── queries/
│   └── dto/
├── repositories/
│   ├── interfaces/
│   └── sqlalchemy/
├── services/
├── use_cases/
├── events/
└── exceptions/
```

---

# How to Create a New Domain Module

Examples:

```text
organizations
tenants
policies
audit_logs
service_accounts
```

Steps:

1. Create Models
2. Create DTOs
3. Create Commands
4. Create Queries
5. Create Repository Interface
6. Create Repository Implementation
7. Create Services
8. Create Use Cases
9. Create API Routes
10. Create Tests

Never skip layers.

---

# How to Create a New Endpoint

Example:

```text
POST /api/v1/organizations/{organization_id}/users
```

Steps:

```text
Request Schema
Response Schema
Command
DTO
Use Case
Route
Authorization Policy
Tests
```

Flow:

```text
Route
 ↓
Use Case
 ↓
Service
 ↓
Repository
```

Routes remain thin.

---

# How to Implement Organization Management

Core Entity:

```text
Organization
```

Represents:

```text
Apple Corp
Orange Tech
Banana Republic
```

Organization owns:

```text
Users
Roles
Policies
Tenants
Groups
Resources
```

Example:

```python
class Organization(Base):
    ...
```

---

# How to Implement Tenant Management

Tenant is:

```text
Workspace
Environment
Business Unit
Project Space
```

Examples:

```text
apple-prod
apple-stage
apple-dev
```

Tenant belongs to:

```text
Organization
```

Relationship:

```text
Organization
     │
     ▼
Tenant
```

Never make Tenant the primary RBAC boundary.

RBAC remains Organization-scoped.

---

# How to Implement Memberships

Membership represents:

```text
User ↔ Organization
```

Example:

```text
Owner
Admin
Moderator
Member
```

Table:

```text
organization_memberships
```

Example:

```python
class OrganizationMembership(Base):
    ...
```

---

# How to Implement Authentication

Modules:

```text
auth
sessions
mfa
```

Required:

```text
JWT
Refresh Tokens
Session Tracking
Password Reset
MFA
Token Revocation
```

Services:

```text
AuthenticationService
JWTService
PasswordService
SessionService
```

Authentication only proves identity.

Authentication does NOT grant access.

---

# How to Implement Authorization

Authorization is a separate domain.

Modules:

```text
authorization
policies
roles
permissions
```

Architecture:

```text
Policy Enforcement Point (PEP)
        ↓
Policy Decision Point (PDP)
        ↓
Decision
```

Example:

```python
decision = authorization_service.authorize(
    subject=user,
    action="user.create",
    resource=organization,
    context=context
)
```

---

# How to Implement RBAC

Modules:

```text
roles
permissions
```

Tables:

```text
roles
permissions
role_permissions
organization_memberships
```

Flow:

```text
User
 ↓
Membership
 ↓
Role
 ↓
Permissions
```

Example:

```text
Owner
Admin
Moderator
Member
```

RBAC grants broad capabilities.

---

# How to Implement ABAC

Modules:

```text
policies
authorization
```

Pattern:

```text
Subject
Resource
Action
Environment
```

Example:

```json
{
  "subject.department": "Engineering",
  "resource.department": "Engineering",
  "action": "resource.read"
}
```

ABAC refines RBAC.

Example:

```text
Admin
+
Department Match
=
Allow
```

---

# How to Create Policies

Location:

```text
modules/policies/
```

Types:

```text
Allow
Deny
Conditional
Time-Based
Tenant-Based
```

Example:

```python
policy_engine.evaluate(
    subject,
    resource,
    action,
    context
)
```

Policies are data.

Never hardcode policies in routes.

---

# How to Implement Multi-Tenancy

Security Boundary:

```text
Organization
```

Workspace Boundary:

```text
Tenant
```

Every entity must contain:

```python
organization_id
```

Optional:

```python
tenant_id
```

Examples:

```python
class Resource(Base):
    organization_id
    tenant_id
```

Repository filtering:

```python
WHERE organization_id = ?
```

must be automatic.

Never trust client-provided organization IDs.

---

# How to Implement Tenant Resolution

Flow:

```text
Workspace Slug
      ↓
Organization Lookup
      ↓
Membership Validation
      ↓
JWT Creation
```

Example:

```text
apple-corp
```

resolves:

```text
org_001
```

---

# How to Implement User Invitations

Flow:

```text
Admin
 ↓
Create Invitation
 ↓
Email Sent
 ↓
Accept Invitation
 ↓
Membership Created
```

Use Cases:

```text
InviteUserUseCase
AcceptInvitationUseCase
```

---

# How to Implement Service Accounts

Modules:

```text
service_accounts
api_keys
```

Used for:

```text
CI/CD
Automation
Integrations
Microservices
```

Never use user accounts for machine access.

---

# How to Implement Audit Logging

Module:

```text
audit_logs
```

Every security-sensitive action must create an audit event.

Examples:

```text
user.created
user.deleted
role.assigned
role.revoked
tenant.created
policy.created
policy.updated
login.success
login.failed
authorization.denied
```

Audit logging occurs in services.

Never in routes.

---

# How to Implement Observability

Every log entry must include:

```json
{
  "organization_id": "org_001",
  "tenant_id": "tenant_prod",
  "user_id": "usr_001",
  "request_id": "req_001",
  "trace_id": "trace_001"
}
```

Metrics:

```text
login_attempts_total
authorization_requests_total
policy_evaluation_total
tenant_resolution_total
audit_events_total
```

---

# How to Implement API Versioning

```text
/api/v1/
/api/v2/
```

Version:

```text
Routes
Requests
Responses
```

Do NOT version:

```text
Services
Repositories
Models
Use Cases
```

---

# How to Implement Dependency Injection

Location:

```text
shared/dependencies/
```

Files:

```text
repositories.py
services.py
use_cases.py
authorization.py
```

Routes depend on:

```text
Use Cases
```

Use Cases depend on:

```text
Services
```

Services depend on:

```text
Repositories
```

---

# How to Implement Pagination

Default:

```text
Cursor Pagination
```

Response:

```json
{
  "items": [],
  "next_cursor": "...",
  "has_next": true
}
```

Never use offset pagination for large tables.

---

# How to Write Tests

Structure:

```text
tests/

├── api/
├── repositories/
├── services/
├── use_cases/
├── authorization/
├── policies/
├── integration/
└── e2e/
```

Test Order:

```text
Repository
Service
Authorization
Use Case
API
Integration
E2E
```

Critical Coverage:

```text
Authentication
Authorization
Policy Evaluation
Tenant Isolation
Audit Logging
```

---

# NutraTenant Rules

Always:

✓ Use Use Cases

✓ Use Service Layer

✓ Use Repository Pattern

✓ Enforce Organization Isolation

✓ Use RBAC + ABAC

✓ Audit Security Events

✓ Use UUIDs

✓ Use Dependency Injection

✓ Use Structured Logging

✓ Use OpenTelemetry

✓ Validate Authorization Centrally

Never:

✗ Business Logic In Routes

✗ Authorization In Routes

✗ Repository Calls From Routes

✗ Hardcoded Policies

✗ Trust Client Tenant IDs

✗ Skip Audit Logging

✗ Skip Authorization Checks

✗ Direct ORM Usage In Routes

✗ Shared Mutable State

✗ Blocking Operations In Async Endpoints
