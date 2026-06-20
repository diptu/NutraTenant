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

### Login — `POST /api/v1/auth/login`
Target contract: `{"username", "password"}` → either `{"status":"MFA_REQUIRED","mfa_token","message"}` or `{"access_token","refresh_token","expires_in","user":{"id","tenant_id","role"}}`.

- [x] User authentication (email/password verification against the Argon2 hash) — `AuthService.login`
- [x] Per-account (not global) rate limiting on login attempts, fails open if Redis is unreachable rather than 500ing the whole login path — `app/core/rate_limit.py`
- [x] Progressive account lockout with exponential backoff on repeated failures — `AuthService._record_failed_login`
- [x] Login audit logging — `auth.login.success` / `auth.login.failure` / `auth.login.locked` / `auth.login.rate_limited` / `auth.login.mfa_challenge_issued`
- [x] Access token generation (short-lived JWT, HS256) — `create_access_token`
- [x] Refresh token generation, persisted server-side for rotation/revocation (not a bare stateless JWT) — `RefreshToken` table
- [ ] Accept the contract's `username` field as the login identifier, aliased internally to the existing `email` lookup (current `LoginRequest` only accepts an `email` key)
- [x] Success response: add `expires_in` (seconds), derived from `settings.access_token_expire_minutes * 60` — `_build_token_response` in `app/api/v1/routes/auth.py`
- [x] Success response: add a `user` object (`id`, `tenant_id`, `role`, …) — resolved the design gap via `AuthService._resolve_tenant`: 0 orgs → no tenant context, 1 org → auto-selected, 2+ orgs without an explicit `tenant_id` → `409 TenantSelectionRequiredError` carrying the candidate list, explicit `tenant_id` not in the caller's memberships → `403`. Shipped a richer nested `tenant`/`role`/`session`/`links` shape (sign-off obtained) rather than the flat `{id,tenant_id,role}` originally sketched here
- [x] Success response: return `refresh_token` in the JSON body — sign-off obtained: kept in the httpOnly cookie **and** added to the body for non-browser clients; `POST /auth/refresh` now accepts it from either (cookie takes precedence) — see `RefreshRequest`
- [ ] Replace the boolean `mfa_required` discriminator with the contract's `status: "MFA_REQUIRED"` + `message` shape, and rename `mfa_challenge_token` → `mfa_token` on the wire — **deliberately declined**: a later request asked for exactly this rename as a "new" `/verify-mfa` endpoint; decided (with sign-off) to extend `/auth/mfa/login-verify` in place instead of forking a near-duplicate endpoint, so the existing field names/shape stand
- [ ] Tenant isolation: reject login when the resolved organization/tenant itself is inactive (`Organization.is_active`), independent of `User.is_active` — still not checked: `_resolve_tenant` validates membership but never `Organization.is_active`
- [x] Tenant isolation: embed a `tenant_id` claim on the access token itself — `create_access_token(..., tenant_id=organization.slug, role=role.name)` in `AuthService._issue_token_pair`

### Multi-Factor Authentication — `POST /api/v1/auth/verify-mfa`
Target contract: `{"mfa_token", "otp"}` → `{"access_token","refresh_token","expires_in"}`.

- [x] TOTP generation/verification (RFC 6238) with 1-step clock-drift tolerance — `app/infrastructure/security/mfa.py`
- [x] TOTP secret encrypted at rest (Fernet — unlike a password, verification needs the original value back, so it can't be one-way hashed)
- [x] Short-lived MFA challenge token issued only *after* password verification succeeds and *before* any access token is minted — `create_mfa_challenge_token`, 5-minute TTL (`mfa_challenge_token_expire_minutes`)
- [x] Challenge token TTL expiration enforced via the JWT `exp` claim — `decode_mfa_challenge_token`
- [x] One-time recovery codes (hashed at rest, consumed on use) as a lost-device fallback to a live TOTP code
- [x] Per-account rate limiting on verify attempts, independent of the login rate limit — bounds brute-forcing a 6-digit code
- [x] MFA enrollment requires a confirm step (valid code against the pending secret) before activating — prevents locking an account out on a half-finished QR scan
- [x] **Single-use enforcement on the `mfa_token`/challenge token itself** — implemented exactly as sketched: the challenge's `jti` is blacklisted via `TokenBlacklist.add_jti` the instant it's successfully redeemed (`_mfa_challenge_blacklist_key`), so a replayed-but-still-cryptographically-valid challenge token now gets `401` immediately
- [x] Per-challenge brute-force lockout (new, beyond what this checklist originally called for): a second, narrower limiter keyed `mfa-challenge-attempts:{jti}` caps attempts against *one* challenge at `_MFA_CHALLENGE_MAX_ATTEMPTS = 3`, independent of the per-account `mfa-verify:{user.id}` limiter above; the 4th attempt blacklists the `jti` outright (a hard lock, not a retry-later throttle) and logs `auth.mfa.challenge_locked`
- [ ] HOTP (event-based OTP, RFC 4226) support, for hardware tokens that aren't time-based — only TOTP exists today
- [ ] Rename route `/auth/mfa/login-verify` → `/auth/verify-mfa`, and fields `code`/`mfa_challenge_token` → `otp`/`mfa_token`, to match the contract exactly — **deliberately declined**, see the matching note under Login above
- [x] Verify-MFA success response: add `refresh_token` (body) + `expires_in`, mirroring the login success contract above — same `_build_token_response` helper serves both `/login` and `/mfa/login-verify`

### Token Refresh & Rotation — `POST /api/v1/auth/refresh`
Target contract: `{"refresh_token"}` → `{"access_token","expires_in"}`.

- [x] Refresh token rotation on every use — old token revoked, new `jti` issued into the same rotation family — `AuthService._issue_token_pair`
- [x] Reuse detection: presenting an already-revoked refresh token revokes the **entire rotation family**, not just that token — `RefreshTokenReusedError`, `auth.refresh.reuse_detected` (a strong signal of token theft, handled distinctly from a merely expired token)
- [x] Expiry validated server-side against the persisted `refresh_tokens.expires_at`, independent of the JWT's own `exp` claim
- [x] Rotation and reuse-detection audit logging — `auth.refresh.rotated` / `auth.refresh.reuse_detected`
- [x] Accept `refresh_token` from the **request body** — `RefreshRequest`, cookie checked first then body fallback in `POST /auth/refresh`
- [x] Response: add `expires_in` (seconds)
- [x] Re-validate on every refresh that the user's organization membership(s) backing their last-issued `tenant_id`/`role` claim are still active — `AuthService.refresh` re-resolves `stored.organization_id` → membership → role fresh from the DB on every rotation (migration `0010_refresh_token_tenant_context`); a revoked membership silently drops tenant context rather than failing the refresh outright

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
- [x] MFA (Multi-Factor Authentication) — TOTP enroll/confirm/disable + login challenge/verify with recovery codes (`AuthService.setup_mfa/confirm_mfa/disable_mfa/verify_mfa_and_login`, `POST /auth/mfa/{setup,confirm,disable,login-verify}`)
- [ ] SSO (OIDC/OAuth2 Providers) — Google OIDC done; no other providers wired up
- [x] Environmental Contexts (IP White-listing, Geo-fencing, Time-bound access) — IP corporate-range + timestamp context and `gt`/`gte`/`lt`/`lte` operators support time-bound conditions; geo-fencing is a deterministic stub (`resolve_geo_stub`) pending a paid geo-IP provider
- [ ] SCIM Provisioning (Syncing user identity and attributes from external IDPs)
- [x] Account Lockout & Token Revocation Lists

## Phase 4: Deployment & Scaling
- [ ] Deploy on Render / Cloud Infrastructure (CD pipeline builds + pushes image to GHCR; no actual deploy step yet)
- [x] Policy Engine caching strategy (Redis for highly requested evaluation matrices) — `app/core/cache.py` Redis-backed permission cache (falls back to in-memory)
