# HOW-TO-AUTH.md

Implementation Playbook for Authentication & Session Management

Domain: Identity & Access Management (IAM)

Service: Authentication Service

Applies To:

```text
/api/v1/auth/*
```

Related Modules:

```text
auth
sessions
mfa
organizations
tenants
memberships
roles
permissions
policies
audit_logs
notifications
```

---

# Purpose

The Authentication Service is responsible for:

* User Registration
* Email Verification
* Authentication
* Multi-Factor Authentication
* JWT Issuance
* Refresh Token Rotation
* Session Management
* Password Management
* Invite Acceptance
* Organization Resolution
* Tenant Context Switching

Authentication proves identity.

Authorization determines access.

Never mix the two.

---

# Architecture

```text
Client
   │
   ▼
Auth API
   │
   ▼
Use Case
   │
   ▼
Authentication Service
   │
   ▼
Session Service
   │
   ▼
Repositories
   │
   ▼
Database
```

Authorization occurs AFTER authentication.

---

# Authentication Flow

```text
Register
    │
    ▼
Verify Email
    │
    ▼
Login
    │
    ▼
MFA Verification
    │
    ▼
Create Session
    │
    ▼
Issue JWT
    │
    ▼
Access APIs
    │
    ▼
Refresh Token
    │
    ▼
Logout
```

---

# Domain Ownership

Authentication Service owns:

```text
credentials
passwords
tokens
sessions
mfa
email_verification
password_reset
```

Authentication Service does NOT own:

```text
roles
permissions
policies
authorization
```

Those belong to IAM and Authorization domains.

---

# JWT Design

Current Recommendation:

```json
{
  "sub": "usr_001",
  "organization_id": "org_001",
  "organization_slug": "apple-corp",
  "active_tenant_id": "tenant_prod",
  "session_id": "sess_001",
  "token_type": "access",
  "iat": 1781966867,
  "exp": 1781970467,
  "jti": "jwt_001"
}
```

Do NOT embed:

```text
permissions
roles
policies
```

inside JWT.

Those should be loaded dynamically.

---

# Access Token Rules

Lifetime:

```text
15 Minutes
```

Recommended:

```text
5-15 Minutes
```

Must Contain:

```text
user identity
organization context
active tenant context
session id
```

Must NOT Contain:

```text
password
mfa secrets
refresh token
```

---

# Refresh Token Rules

Lifetime:

```text
7-30 Days
```

Requirements:

```text
Rotation Enabled
Revocable
Stored Hashed
Device Bound
```

Never store refresh tokens in plain text.

---

# Registration

Endpoint:

```http
POST /auth/register
```

Use Case:

```text
RegisterUserUseCase
```

Workflow:

```text
Validate Input
    ↓
Validate Password Policy
    ↓
Check Email Uniqueness
    ↓
Create User
    ↓
Create Pending Membership
    ↓
Generate Verification Token
    ↓
Send Verification Email
    ↓
Audit Log
```

Initial Status:

```text
PENDING_VERIFICATION
```

Audit Event:

```text
auth.registered
```

---

# Email Verification

Endpoint:

```http
POST /auth/verify-email
```

Workflow:

```text
Validate Token
    ↓
Check Expiration
    ↓
Mark Email Verified
    ↓
Activate User
    ↓
Audit Log
```

Audit Event:

```text
auth.email_verified
```

---

# Login

Endpoint:

```http
POST /auth/login
```

Use Case:

```text
LoginUserUseCase
```

Workflow:

```text
Find User
    ↓
Verify Password
    ↓
Validate Status
    ↓
Check MFA Requirement
    ↓
Create Session
    ↓
Issue Tokens
```

Valid Statuses:

```text
ACTIVE
```

Denied Statuses:

```text
PENDING_VERIFICATION
LOCKED
SUSPENDED
DELETED
```

Audit Events:

```text
auth.login_success
auth.login_failed
```

---

# MFA Verification

Endpoint:

```http
POST /auth/verify-mfa
```

Workflow:

```text
Validate Challenge
    ↓
Verify OTP
    ↓
Issue Tokens
    ↓
Create Session
```

Supported Methods:

```text
Authenticator App
Email OTP
SMS OTP
Security Key
```

Recommended:

```text
TOTP Authenticator App
```

Audit Events:

```text
auth.mfa_success
auth.mfa_failed
```

---

# Session Creation

Every successful login creates:

```text
Session
```

Session Stores:

```text
device_id
device_name
browser
platform
ip_address
timezone
user_agent
```

Example:

```json
{
  "session_id": "sess_001",
  "user_id": "usr_001",
  "device_name": "MacBook Pro",
  "ip_address": "203.0.113.10"
}
```

---

# Refresh Token

Endpoint:

```http
POST /auth/refresh
```

Workflow:

```text
Validate Refresh Token
    ↓
Check Revocation
    ↓
Rotate Refresh Token
    ↓
Issue New Access Token
    ↓
Update Session
```

Audit Event:

```text
auth.token_refreshed
```

---

# Logout

Endpoint:

```http
POST /auth/logout
```

Workflow:

```text
Identify Session
    ↓
Revoke Session
    ↓
Blacklist Access Token
    ↓
Revoke Refresh Token
```

Audit Event:

```text
auth.logout
```

---

# Forgot Password

Endpoint:

```http
POST /auth/forgot-password
```

Workflow:

```text
Validate Email
    ↓
Generate Reset Token
    ↓
Store Token
    ↓
Send Email
```

Do not reveal:

```text
Whether email exists
```

Always return:

```json
{
  "success": true
}
```

Audit Event:

```text
auth.password_reset_requested
```

---

# Reset Password

Endpoint:

```http
POST /auth/reset-password
```

Workflow:

```text
Validate Reset Token
    ↓
Validate Password Policy
    ↓
Update Password
    ↓
Invalidate Sessions
    ↓
Audit Log
```

Audit Event:

```text
auth.password_reset_completed
```

---

# Change Password

Endpoint:

```http
POST /auth/change-password
```

Workflow:

```text
Validate Current Password
    ↓
Validate New Password
    ↓
Update Password
    ↓
Revoke Other Sessions
```

Audit Event:

```text
auth.password_changed
```

---

# Invite Acceptance

Endpoint:

```http
POST /auth/accept-invite
```

Workflow:

```text
Validate Invite Token
    ↓
Create Credentials
    ↓
Activate Membership
    ↓
Create Session
    ↓
Issue JWT
```

Audit Event:

```text
auth.invite_accepted
```

---

# Organization Resolution

Authentication must resolve:

```text
Organization
```

before issuing JWT.

Example:

```text
apple-corp
```

resolves:

```text
org_001
```

JWT should contain:

```text
organization_id
organization_slug
```

---

# Tenant Switching

Endpoint:

```http
POST /auth/switch-tenant
```

Purpose:

Switch active workspace.

Example:

```text
apple-prod
    ↓
apple-stage
```

Workflow:

```text
Validate Membership
    ↓
Validate Tenant Access
    ↓
Create New Access Token
    ↓
Update Session Context
```

Audit Event:

```text
auth.tenant_switched
```

---

# Session Management

Session Service owns:

```text
active_sessions
refresh_tokens
revocations
device_tracking
```

Endpoints:

```text
GET    /users/{id}/sessions
DELETE /users/{id}/sessions/{session_id}
```

Authentication Service orchestrates.

---

# Password Policy

Minimum:

```text
12 Characters
Uppercase
Lowercase
Number
Special Character
```

Reject:

```text
Common Passwords
Breached Passwords
Reused Passwords
```

---

# Security Controls

Required:

```text
Argon2 Password Hashing
Refresh Token Rotation
Short-Lived Access Tokens
Session Tracking
MFA Support
Rate Limiting
Audit Logging
```

Recommended:

```text
Passkeys
WebAuthn
Device Trust
Risk-Based Authentication
```

---

# Authorization Boundary

Authentication Service MUST NOT:

```text
Evaluate Policies
Assign Permissions
Make Authorization Decisions
```

Instead:

```text
Authentication
     ↓
Authorization Service
```

---

# Audit Logging

Required Events:

```text
auth.registered
auth.email_verified

auth.login_success
auth.login_failed

auth.mfa_success
auth.mfa_failed

auth.logout

auth.password_reset_requested
auth.password_reset_completed

auth.password_changed

auth.invite_accepted

auth.tenant_switched

auth.token_refreshed
```

Audit logging occurs inside services.

Never in routes.

---

# Observability

Every log must contain:

```json
{
  "organization_id": "org_001",
  "tenant_id": "tenant_prod",
  "user_id": "usr_001",
  "session_id": "sess_001",
  "request_id": "req_001",
  "trace_id": "trace_001"
}
```

Metrics:

```text
login_attempts_total
login_success_total
login_failure_total

mfa_success_total
mfa_failure_total

active_sessions_total

password_reset_total

refresh_token_rotations_total

tenant_switch_total
```

---

# Testing Requirements

Repository Tests:

```text
User Lookup
Token Storage
Session Storage
Refresh Rotation
```

Service Tests:

```text
Register User
Verify Email
Login
MFA
Refresh Token
Logout
Password Reset
Change Password
Switch Tenant
```

Security Tests:

```text
JWT Validation
Token Replay
Refresh Rotation
Session Revocation
Password Policy
Rate Limiting
```

Integration Tests:

```text
Register → Verify → Login

Login → MFA → Access

Refresh → Logout

Invite → Accept → Login

Tenant Switch
```

---

# Rules

Always:

✓ Hash Passwords With Argon2

✓ Rotate Refresh Tokens

✓ Use MFA

✓ Audit Authentication Events

✓ Track Sessions

✓ Resolve Organization Context

✓ Resolve Active Tenant Context

✓ Use Use Cases

✓ Use Service Layer

✓ Use Repository Pattern

✓ Revoke Tokens On Logout

Never:

✗ Store Plaintext Passwords

✗ Store Plaintext Refresh Tokens

✗ Embed Permissions In JWT

✗ Perform Authorization Logic

✗ Trust Client Organization IDs

✗ Skip Audit Logging

✗ Skip Session Tracking

✗ Hardcode Secrets

```
```
