# Multi-Tenant RBAC + ABAC IAM Checklist

## 1. Project Setup
- [] Create IAM service repository
- [] Configure project structure
- [] Setup environment variables
- [] Configure logging
- [] Setup database and migrations (Ensure support for dynamic attributes/JSONB schemas)
- [] Configure testing and CI/CD

## 2. Authentication
### Registration
- [] User registration
- [] Email uniqueness validation
- [] Password hashing
- [] JWT token generation

### Login
- [] User authentication
- [] Access token generation (Inject static user attributes into token claims if needed)
- [] Refresh token generation
- [] Login audit logging

### Password Management
- [] Change password
- [] Forgot password
- [] Password reset flow

### Federated Identity (OAuth2 / OIDC)
- [] Configure OAuth2 state/nonce mechanism for CSRF mitigation
- [] Implement Google login redirection endpoint
- [] Implement Google OAuth2 backend callback handler
- [] Extract claims from verified ID tokens and map to local user profiles and default attributes

## 3. User Management & Attribute Profiling
- [] User CRUD
- [] User profile management
- [] User activation/deactivation
- [] User search and filtering
- [ ]  Define and manage User Attributes (e.g., Department, Clearance Level, Cost Center)
- [ ] Tenant-level attribute mapping (for multi-tenant isolation)

## 4. Organization & Resource Management
- [ ] Create organization
- [ ] Update organization
- [ ] Delete organization
- [ ] Organization membership management
- [ ] Resource Classification Schema (Registering resources with metadata tags like `Confidentiality=High`, `OwnerID=X`, `Region=EU`)

## 5. Role Management (Coarse-Grained Layer)
- [ ] Seed default roles (e.g., Admin, Member, Guest)
- [ ] Create custom roles
- [ ] Update roles
- [ ] Delete roles
- [ ] Assign roles to users

## 6. ABAC Policy & Rule Management (Fine-Grained Layer)
- [ ]  Design Policy Schema (Defining Subjects, Actions, Resources, and Contextual Conditions)
- [ ]  Implement Policy Engine / PDP (Policy Decision Point) integration (e.g., OPA, Casbin, or custom json-rules-engine)
- [ ]  Policy CRUD (Create/Update dynamic evaluation rules, e.g., `Allow if User.Dept == Resource.Dept AND Context.IP within CorporateRange`)
- [ ]  Policy Conflict Resolution Strategies (e.g., Deny-Overrides vs. Allow-Overrides)

## 7. Authorization & Evaluation Middleware
- [ ] JWT validation middleware
- [ ] Role-based authorization middleware (Fast path/Coarse filtering)
- [ ]  Attribute extraction middleware (Parses incoming request context: IP, Timestamp, Geo-location)
- [ ]  Advanced Authorization Middleware (Combines Subject + Resource + Environment attributes for evaluation)
- [ ] Protect API endpoints with dual RBAC-ABAC guards

## 8. Audit Logging & Policy Tracing
- [ ] Login/Logout events
- [ ] Password changes
- [ ] Role assignments
- [ ] Policy changes (Who updated an authorization rule)
- [ ] Policy Evaluation Tracing (Log *why* an ABAC policy denied access, capturing the exact state of attributes at evaluation time)

## 9. Security
- [ ] Rate limiting
- [ ] Account lockout
- [ ] Token revocation
- [ ] Input validation (Specifically validating complex JSON/boolean policy strings)
- [ ] Security headers

## 10. Testing
- [ ] Unit tests
- [ ] Integration tests
- [ ]  Matrix-based Policy Evaluation testing (Verifying edge cases for complex attribute rules)
- [ ] Security tests (Privilege escalation and attribute tampering mitigation)

## 11. Production Readiness
- [ ] Health checks
- [ ] Metrics endpoint (Track Policy Evaluation Latency—critical for ABAC)
- [ ] Monitoring and alerting
- [ ] Backup and recovery

---

# MVP Priority (Updated for ABAC Integration)

## Phase 1: Core Authentication & Hybrid Foundations
- [ ] Registration & Login
- [ ] JWT Authentication & Request Context parsing
- [ ] User, Role, and Resource Profile CRUD (with basic attribute mapping)
- [ ] Core Authorization Middleware (Evaluating basic RBAC roles + dynamic resource ownership check)

## Phase 2: Complete ABAC Engine & Operations
- [ ] Dynamic Policy Engine Integration (Full Boolean Logic handling)
- [ ] Refresh Tokens
- [ ] Invitations & Organization Membership Management
- [ ] Policy Change Logs & Evaluation Tracing

## Phase 3: Enterprise Scale & Advanced Contexts
- [ ] MFA (Multi-Factor Authentication)
- [ ] SSO (OIDC/OAuth2 Providers)
- [ ] Environmental Contexts (IP White-listing, Geo-fencing, Time-bound access)
- [ ] SCIM Provisioning (Syncing user identity and attributes from external IDPs)
- [ ] Account Lockout & Token Revocation Lists

## Phase 4: Deployment & Scaling
- [ ] Deploy on Render / Cloud Infrastructure
- [ ] Policy Engine caching strategy (Redis for highly requested evaluation matrices)
