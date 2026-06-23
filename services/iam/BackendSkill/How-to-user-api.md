# HOW-TO-USER-API.md

Implementation Playbook for User Management

Domain: Identity & Access Management (IAM)

Service: User Service

Applies To:

```text
/api/v1/users/*
```

Related Modules:

```text
users
organizations
memberships
roles
permissions
policies
authorization
audit_logs
sessions
```

---

# Purpose

The User Service manages:

* User Profiles
* User Lifecycle
* Organization Memberships
* Tenant Memberships
* Role Assignments
* Permission Assignments
* User Attributes (ABAC)
* Session Management
* User Search
* User Status

The User Service is one of the core IAM domains.

---

# Architecture

```text
Route
  ↓
Use Case
  ↓
User Service
  ↓
Authorization Service
  ↓
Repositories
  ↓
Database
```

Authorization must execute before any mutation.

---

# Domain Ownership

User Service owns:

```text
users
user_profiles
user_attributes
user_status
```

User Service does NOT own:

```text
roles
permissions
policies
sessions
```

Those belong to dedicated modules.

---

# API Coverage

```text
GET    /users/me
GET    /users/{id}

POST   /users
PUT    /users/{id}
DELETE /users/{id}

GET    /users
GET    /users/search

PATCH  /users/{id}/status

POST   /users/{id}/roles
DELETE /users/{id}/roles/{role_id}

POST   /users/{id}/permissions
DELETE /users/{id}/permissions

GET    /users/{id}/sessions
DELETE /users/{id}/sessions/{session_id}

POST   /users/{id}/tenants
DELETE /users/{id}/tenants/{tenant_id}
```

---

# User Model Guidelines

Location:

```text
modules/users/models/user.py
```

Required Fields:

```python
id
organization_id
email
username
name
phone
status
email_verified
mfa_enabled
created_at
updated_at
last_login
```

Never store:

```text
Roles
Permissions
Policies
```

inside User.

Relationships only.

---

# User Status Lifecycle

Allowed States:

```text
PENDING_VERIFICATION
ACTIVE
INACTIVE
SUSPENDED
LOCKED
DELETED
```

Flow:

```text
PENDING_VERIFICATION
           │
           ▼
        ACTIVE
           │
 ┌─────────┼─────────┐
 ▼         ▼         ▼
LOCKED  INACTIVE  SUSPENDED
           │
           ▼
        DELETED
```

Rules:

```text
DELETED cannot login
LOCKED cannot login
SUSPENDED cannot login
```

---

# Get Current User

Endpoint:

```http
GET /users/me
```

Purpose:

```text
Resolve current authenticated user
```

Workflow:

```text
JWT
 ↓
Authentication Service
 ↓
Load Membership
 ↓
Load Roles
 ↓
Load Permissions
 ↓
Load Attributes
 ↓
Return Profile
```

Never trust JWT claims as source of truth.

Always reload membership.

---

# Create User

Endpoint:

```http
POST /users
```

Use Case:

```text
CreateUserUseCase
```

Workflow:

```text
Validate Request
 ↓
Authorize user.create
 ↓
Check email uniqueness
 ↓
Create User
 ↓
Create Membership
 ↓
Assign Default Role
 ↓
Publish Event
 ↓
Audit Log
```

Audit Event:

```text
user.created
```

---

# Update User

Endpoint:

```http
PUT /users/{id}
```

Authorization:

```text
user.update
```

Rules:

```text
User may update own profile

Admin may update any user

Owner may update any user
```

Audit Event:

```text
user.updated
```

---

# Delete User

Endpoint:

```http
DELETE /users/{id}
```

Recommended:

Soft Delete

```python
status = "DELETED"
```

Avoid hard deletes.

Audit Event:

```text
user.deleted
```

---

# List Users

Endpoint:

```http
GET /users
```

Supports:

```text
status
role
department
designation
location
tenant
```

Repository must automatically enforce:

```sql
WHERE organization_id = :organization_id
```

Never expose users from another organization.

---

# Search Users

Endpoint:

```http
GET /users/search
```

Search Fields:

```text
name
email
username
phone
```

Requirements:

```text
Organization scoped
Tenant scoped
Permission checked
```

---

# User Attributes (ABAC)

Stored In:

```text
user_attributes
```

Examples:

```json
{
  "department": "Finance",
  "designation": "Manager",
  "location": "Dhaka",
  "clearance_level": 5
}
```

Attributes are used by Policy Engine.

Example:

```json
{
  "subject.department": "Finance",
  "resource.department": "Finance"
}
```

Result:

```text
ALLOW
```

---

# Assign Role

Endpoint:

```http
POST /users/{id}/roles
```

Use Case:

```text
AssignRoleUseCase
```

Workflow:

```text
Authorize role.assign
 ↓
Validate Role
 ↓
Create Membership Role
 ↓
Audit Event
```

Audit Event:

```text
role.assigned
```

---

# Remove Role

Endpoint:

```http
DELETE /users/{id}/roles/{role_id}
```

Rules:

```text
Cannot remove Owner role from last owner
```

Audit Event:

```text
role.removed
```

---

# Direct Permission Assignment

Endpoint:

```http
POST /users/{id}/permissions
```

Purpose:

Exceptional access only.

Preferred:

```text
Role → Permission
```

Avoid:

```text
User → Permission
```

unless explicitly required.

Audit Event:

```text
permission.assigned
```

---

# Session Management

Endpoints:

```http
GET /users/{id}/sessions
DELETE /users/{id}/sessions/{session_id}
```

Sessions belong to:

```text
Authentication Service
```

User Service only orchestrates.

Workflow:

```text
Load Sessions
 ↓
Validate Access
 ↓
Return Sessions
```

Revocation:

```text
Session Revoked
 ↓
Token Blacklisted
 ↓
Audit Event
```

---

# Tenant Membership Management

Endpoints:

```http
POST   /users/{id}/tenants
DELETE /users/{id}/tenants/{tenant_id}
```

Purpose:

Assign user to:

```text
apple-prod
apple-stage
apple-dev
```

Workflow:

```text
Authorize tenant.assign
 ↓
Validate Tenant
 ↓
Create Membership
 ↓
Audit Event
```

Audit Event:

```text
tenant.member_added
tenant.member_removed
```

---

# Authorization Requirements

Every endpoint must execute:

```python
authorization_service.authorize(
    subject=user,
    action=action,
    resource=resource,
    context=context
)
```

Never perform authorization inside routes.

---

# Required Permissions

```text
user.read
user.create
user.update
user.delete

role.assign
role.remove

permission.assign
permission.remove

tenant.assign
tenant.remove

session.read
session.revoke
```

---

# Audit Logging

Required Events:

```text
user.created
user.updated
user.deleted

user.status_changed

role.assigned
role.removed

permission.assigned
permission.removed

tenant.member_added
tenant.member_removed

session.revoked
```

Audit logging occurs in services.

Never in routes.

---

# Observability

Every log must include:

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
users_created_total
users_updated_total
users_deleted_total

roles_assigned_total
permissions_assigned_total

tenant_memberships_total

session_revocations_total
```

---

# Testing Requirements

Repository Tests:

```text
User CRUD
User Search
Tenant Isolation
```

Service Tests:

```text
Create User
Update User
Delete User
Assign Role
Assign Permission
Tenant Membership
```

Authorization Tests:

```text
Owner Access
Admin Access
Moderator Access
Member Access
Cross-Tenant Denial
Cross-Organization Denial
```

Integration Tests:

```text
User Lifecycle
Role Assignment
Permission Assignment
Tenant Membership Assignment
Session Revocation
```

---

# Rules

Always:

✓ Organization Scoped

✓ Tenant Aware

✓ RBAC + ABAC Protected

✓ Audit Logged

✓ Use Use Cases

✓ Use Service Layer

✓ Use Repository Pattern

✓ Validate Permissions Centrally

✓ Soft Delete Users

✓ Publish Domain Events

Never:

✗ Trust Client Organization IDs

✗ Hardcode Roles

✗ Hardcode Permissions

✗ Perform Authorization In Routes

✗ Direct ORM Usage In Routes

✗ Skip Audit Logging

✗ Hard Delete Users

```
```
