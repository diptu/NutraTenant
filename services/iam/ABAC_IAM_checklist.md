# Multi-Tenant RBAC + ABAC IAM Checklist

## 1. Project Setup
- [x] Create IAM service repository
- [x] Configure project structure
- [x] Setup environment variables
- [x] Configure logging
- [x] Setup database and migrations (Ensure support for dynamic attributes/JSONB schemas)
- [x] Configure testing and CI/CD (`.github/workflows/ci.yml` lint+test, `cd.yml` build+push to GHCR on `main`)

## 2. Authentication
### Registration
- [x] User registration
- [x] Email uniqueness validation
- [x] Password hashing
- [x] JWT token generation

### Login
- [x] User authentication
- [x] Access token generation (Inject static user attributes into token claims if needed)
- [x] Refresh token generation
- [x] Login audit logging

### Password Management
- [x] Change password
- [x] Forgot password
- [x] Password reset flow

### Federated Identity (OAuth2 / OIDC)
- [x] Configure OAuth2 state/nonce mechanism for CSRF mitigation
- [x] Implement Google login redirection endpoint
- [x] Implement Google OAuth2 backend callback handler
- [x] Extract claims from verified ID tokens and map to local user profiles and default attributes

## 3. User Management & Attribute Profiling
- [x] User CRUD
- [x] User profile management
- [x] User activation/deactivation
- [x] User search and filtering
- [x] Define and manage User Attributes (e.g., Department, Clearance Level, Cost Center)
- [x] Tenant-level attribute mapping (for multi-tenant isolation)

## 4. Organization & Resource Management
- [x] Create organization
- [x] Update organization
- [x] Delete organization
- [x] Organization membership management
- [x] Resource Classification Schema (Registering resources with metadata tags like `Confidentiality=High`, `OwnerID=X`, `Region=EU`)

## 5. Role Management (Coarse-Grained Layer)
- [x] Seed default roles (e.g., Admin, Member, Guest) — `app/services/rbac_seed.py`, idempotent, `POST /roles/seed`
- [x] Create custom roles
- [x] Update roles
- [x] Delete roles (system roles protected from modify/delete — see `test_system_role_cannot_be_modified_or_deleted`)
- [x] Assign roles to users (+ revoke; org-scoped via `UserOrganizationRole`)

## 6. ABAC Policy & Rule Management (Fine-Grained Layer)
- [x]  Design Policy Schema (Defining Subjects, Actions, Resources, and Contextual Conditions) — `app/infrastructure/db/models/policy.py`
- [x]  Implement Policy Engine / PDP (Policy Decision Point) integration — custom engine in `app/services/policy_engine_service.py` + `app/domain/policy_conditions.py` (non-Turing-complete boolean condition DSL, no `eval()`)
- [x]  Policy CRUD (Create/Update dynamic evaluation rules, e.g., `Allow if User.Dept == Resource.Dept AND Context.IP within CorporateRange`)
- [x]  Policy Conflict Resolution Strategies — deny-overrides implemented; no matching policy = default deny

## 7. Authorization & Evaluation Middleware
- [x] JWT validation middleware
- [x] Role-based authorization middleware (Fast path/Coarse filtering) — `require_global_role` in `app/api/v1/dependencies.py`
- [x]  Attribute extraction middleware (Parses incoming request context: IP, Timestamp, Geo-location) — `app/core/context_middleware.py` (geo-IP is a deterministic stub pending a paid provider)
- [x]  Advanced Authorization Middleware (Combines Subject + Resource + Environment attributes for evaluation) — `PolicyEngineService`
- [x] Protect API endpoints with dual RBAC-ABAC guards

## 8. Audit Logging & Policy Tracing
- [x] Login/Logout events
- [x] Password changes
- [x] Role assignments
- [x] Policy changes (Who updated an authorization rule) — `abac.policy.created/updated/deleted` events
- [x] Policy Evaluation Tracing (Log *why* an ABAC policy denied access, capturing the exact state of attributes at evaluation time) — `policy_evaluation_logs` table, one row per PDP decision

## 9. Security
- [x] Rate limiting — `app/core/rate_limit.py` (in-memory + Redis-backed), wired into login
- [x] Account lockout
- [x] Token revocation
- [x] Input validation (Specifically validating complex JSON/boolean policy strings) — `ConditionError` in `app/domain/policy_conditions.py`, malformed conditions rejected at the API layer
- [x] Security headers

## 10. Testing
- [x] Unit tests
- [x] Integration tests
- [x]  Matrix-based Policy Evaluation testing (Verifying edge cases for complex attribute rules) — `tests/test_hardened_authorization.py` (default-deny, deny-overrides, wildcard deny, attribute/context-bound conditions)
- [x] Security tests (Privilege escalation and attribute tampering mitigation) — `TestHostileCrossTenantAdministration` in `tests/test_authorization_engine.py`

## 11. Production Readiness
- [x] Health checks — `GET /health`
- [x] Metrics endpoint (Track Policy Evaluation Latency—critical for ABAC) — `GET /metrics`, Prometheus format (`iam_http_requests_total`, `iam_http_request_duration_seconds`)
- [ ] Monitoring and alerting (metrics are exposed; no dashboards/alert rules wired up yet)
- [ ] Backup and recovery

---

# MVP Priority (Updated for ABAC Integration)

## Phase 1: Core Authentication & Hybrid Foundations
- [x] Registration & Login
- [x] JWT Authentication & Request Context parsing
- [x] User, Role, and Resource Profile CRUD (with basic attribute mapping)
- [x] Core Authorization Middleware (Evaluating basic RBAC roles + dynamic resource ownership check)

## Phase 2: Complete ABAC Engine & Operations
- [x] Dynamic Policy Engine Integration (Full Boolean Logic handling) — `all`/`any`/`not` + leaf comparisons in `app/domain/policy_conditions.py`
- [x] Refresh Tokens
- [x] Invitations & Organization Membership Management — membership add/update-role/remove plus token-based email-invite flow for non-members (`OrganizationService.invite_member/accept_invitation`, `POST /organizations/{id}/invitations`, `POST /organizations/invitations/accept`)
- [x] Policy Change Logs & Evaluation Tracing

## Phase 3: Enterprise Scale & Advanced Contexts
- [ ] MFA (Multi-Factor Authentication)
- [ ] SSO (OIDC/OAuth2 Providers) — Google OIDC done; no other providers wired up
- [x] Environmental Contexts (IP White-listing, Geo-fencing, Time-bound access) — IP corporate-range + timestamp context and `gt`/`gte`/`lt`/`lte` operators support time-bound conditions; geo-fencing is a deterministic stub (`resolve_geo_stub`) pending a paid geo-IP provider
- [ ] SCIM Provisioning (Syncing user identity and attributes from external IDPs)
- [x] Account Lockout & Token Revocation Lists

## Phase 4: Deployment & Scaling
- [ ] Deploy on Render / Cloud Infrastructure (CD pipeline builds + pushes image to GHCR; no actual deploy step yet)
- [x] Policy Engine caching strategy (Redis for highly requested evaluation matrices) — `app/core/cache.py` Redis-backed permission cache (falls back to in-memory)
