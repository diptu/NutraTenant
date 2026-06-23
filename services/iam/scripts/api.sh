#!/usr/bin/env bash
# Smoke-tests every IAM HTTP endpoint, in dependency order, against a running
# instance of this service (uv run uvicorn app.main:app).
#
# Requires: curl, jq, python3 (for TOTP codes — pyotp is already a project
# dependency, see app/infrastructure/security/mfa.py).
#
# Requires an existing superuser to exercise the superuser-only endpoints
# (organizations/tenants/admin/policies/roles creation) — see
# scripts/create_superuser.py if you don't have one yet:
#   uv run python scripts/create_superuser.py <email> <password>
#
# Usage:
#   ./scripts/api.sh
#   BASE_URL=http://localhost:8000 SUPERUSER_EMAIL=... SUPERUSER_PASSWORD=... ./scripts/api.sh
#
# Every test user/org/tenant created here is suffixed with a per-run epoch
# timestamp (RUN_ID) so repeat runs never collide with each other.

set -uo pipefail

command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required (brew install jq)" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv is required" >&2; exit 1; }

IAM_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Computes a live TOTP code for a base32 secret, via the project's own venv
# (pyotp is already a dependency — see app/infrastructure/security/mfa.py) —
# the system python3 won't have it installed.
totp_code() {
  ( cd "$IAM_DIR" && uv run python3 -c "import pyotp,sys; print(pyotp.TOTP(sys.argv[1]).now())" "$1" )
}

BASE_URL="${BASE_URL:-http://localhost:8000}"
API="${BASE_URL}/api/v1"
SUPERUSER_EMAIL="${SUPERUSER_EMAIL:-diptunazmulalam@gmail.com}"
SUPERUSER_PASSWORD="${SUPERUSER_PASSWORD:-Hello123}"
RUN_ID="$(date +%s)"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

BOLD=$'\033[1m'; RESET=$'\033[0m'; GREEN=$'\033[32m'; RED=$'\033[31m'; CYAN=$'\033[36m'; YELLOW=$'\033[33m'

PASS_COUNT=0
FAIL_COUNT=0

section() {
  printf "\n${BOLD}${CYAN}========== %s ==========${RESET}\n" "$1"
}

note() {
  printf "${YELLOW}NOTE:${RESET} %s\n" "$1"
}

# request METHOD PATH TOKEN DATA EXPECTED_STATUS LABEL [--cookies]
# Sets globals RESP_BODY / RESP_STATUS for the caller to inspect afterward.
request() {
  local method="$1" path="$2" token="$3" data="$4" expected="$5" label="$6" use_cookies="${7:-}"
  local url="${API}${path}"
  local -a curl_args=(-sS -X "$method" "$url" -H "Content-Type: application/json")
  [[ -n "$token" ]] && curl_args+=(-H "Authorization: Bearer ${token}")
  [[ -n "$data" ]] && curl_args+=(-d "$data")
  if [[ "$use_cookies" == "--cookies" ]]; then
    curl_args+=(-c "$COOKIE_JAR" -b "$COOKIE_JAR")
  fi

  local raw
  raw="$(curl "${curl_args[@]}" -w $'\n%{http_code}')"
  RESP_BODY="$(printf '%s' "$raw" | sed '$d')"
  RESP_STATUS="$(printf '%s' "$raw" | tail -n1)"

  if [[ "$RESP_STATUS" == "$expected" ]]; then
    printf "${GREEN}PASS${RESET} [%s] %-6s %-45s %s\n" "$RESP_STATUS" "$method" "$path" "$label"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    printf "${RED}FAIL${RESET} [%s, expected %s] %-6s %-45s %s\n" "$RESP_STATUS" "$expected" "$method" "$path" "$label"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
  printf '%s\n' "$RESP_BODY" | (jq -C . 2>/dev/null || cat)
}

jf() { # jf <jq filter> — reads RESP_BODY
  printf '%s' "$RESP_BODY" | jq -r "$1" 2>/dev/null
}

# ---------------------------------------------------------------------------
section "0. Preflight"
# ---------------------------------------------------------------------------

# /health is mounted at the app root, not under /api/v1 — hit it directly.
HEALTH_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}/health")"
if [[ "$HEALTH_STATUS" == "200" ]]; then
  printf "${GREEN}PASS${RESET} [200] GET    /health -> service reachable\n"
else
  printf "${RED}FAIL${RESET} [%s] GET    /health -> is the server running at %s?\n" "$HEALTH_STATUS" "$BASE_URL"
fi

# Best-effort: seed the global RBAC permission catalog directly (no HTTP
# endpoint creates Permission rows — app.services.rbac_seed.seed_rbac_catalog
# is normally only ever called from tests). Without this, the
# roles/{id}/permissions step below will 404 ("unknown permission code").
note "Seeding the platform permission catalog directly via rbac_seed (best-effort, idempotent)..."
( cd "$IAM_DIR" && uv run python3 -c "
import asyncio
from app.infrastructure.db.session import async_session_factory
from app.services.rbac_seed import seed_rbac_catalog

async def main():
    async with async_session_factory() as s:
        await seed_rbac_catalog(s)
        await s.commit()

asyncio.run(main())
" 2>&1 | tail -3 ) || note "permission-catalog seed failed — roles/{id}/permissions step below will likely 404"

# ---------------------------------------------------------------------------
section "1. AUTH — register & login"
# ---------------------------------------------------------------------------

ALICE_EMAIL="alice-${RUN_ID}@example.com"
BOB_EMAIL="bob-${RUN_ID}@example.com"
PW_EMAIL="pwuser-${RUN_ID}@example.com"
PASSWORD="Password123!"

request POST "/auth/register" "" "{\"email\":\"${ALICE_EMAIL}\",\"password\":\"${PASSWORD}\",\"full_name\":\"Alice\"}" "201" "register alice"
ALICE_ID="$(jf '.id')"

request POST "/auth/register" "" "{\"email\":\"${BOB_EMAIL}\",\"password\":\"${PASSWORD}\",\"full_name\":\"Bob\"}" "201" "register bob"
BOB_ID="$(jf '.id')"

request POST "/auth/register" "" "{\"email\":\"${PW_EMAIL}\",\"password\":\"${PASSWORD}\",\"full_name\":\"PwUser\"}" "201" "register pwuser"

# Alice's login goes through the cookie jar — used later for /auth/refresh
# and /auth/switch-tenant to also demonstrate the cookie-based refresh path.
request POST "/auth/login" "" "{\"email\":\"${ALICE_EMAIL}\",\"password\":\"${PASSWORD}\"}" "200" "login alice" --cookies
ALICE_TOKEN="$(jf '.access_token')"

request POST "/auth/login" "" "{\"email\":\"${BOB_EMAIL}\",\"password\":\"${PASSWORD}\"}" "200" "login bob"
BOB_TOKEN="$(jf '.access_token')"

request POST "/auth/login" "" "{\"email\":\"${SUPERUSER_EMAIL}\",\"password\":\"${SUPERUSER_PASSWORD}\"}" "200" "login superuser"
SU_TOKEN="$(jf '.access_token')"
if [[ -z "$SU_TOKEN" || "$SU_TOKEN" == "null" ]]; then
  note "No superuser session — every superuser-only step below will FAIL. Create one with scripts/create_superuser.py first."
fi

# ---------------------------------------------------------------------------
section "2. USERS"
# ---------------------------------------------------------------------------

request GET "/users/me" "$ALICE_TOKEN" "" "200" "alice reads her own profile"

request GET "/users?q=alice" "$SU_TOKEN" "" "200" "superuser searches users"

request GET "/users/${ALICE_ID}" "$SU_TOKEN" "" "200" "superuser reads alice by id"

request PATCH "/users/${ALICE_ID}" "$ALICE_TOKEN" '{"full_name":"Alice Updated"}' "200" "alice updates her own name"

request PATCH "/users/${BOB_ID}/attributes" "$SU_TOKEN" '{"attributes":{"department":"Engineering"}}' "200" "superuser sets bob's ABAC attributes"

request POST "/users/${BOB_ID}/deactivate" "$SU_TOKEN" "" "200" "superuser deactivates bob"
request POST "/users/${BOB_ID}/activate" "$SU_TOKEN" "" "200" "superuser reactivates bob"

# ---------------------------------------------------------------------------
section "3. ORGANIZATIONS (creation is superuser-only)"
# ---------------------------------------------------------------------------

ORG_SLUG="acme-${RUN_ID}"

request POST "/organizations" "$SU_TOKEN" "{\"name\":\"Acme Inc\",\"slug\":\"${ORG_SLUG}\",\"description\":\"Demo org\"}" "201" "superuser creates organization"
ORG_ID="$(jf '.id')"

request GET "/organizations" "$ALICE_TOKEN" "" "200" "alice lists her organizations (none yet)"

request GET "/organizations/${ORG_ID}" "$SU_TOKEN" "" "200" "superuser reads the organization"

request POST "/organizations/${ORG_ID}/members" "$SU_TOKEN" "{\"user_id\":\"${ALICE_ID}\",\"role_code\":\"member\"}" "201" "superuser adds alice as a member"

request PATCH "/organizations/${ORG_ID}" "$SU_TOKEN" '{"default_attributes":{"region":"EU"}}' "200" "superuser updates org default attributes"

# POST /users — Common User Object response, distinct from POST /admin/users'
# narrower {user_id, status, temp_password_sent} contract (section 5 below).
# No password in the body: a temp one is generated server-side, same flow.
JANE_EMAIL="jane-${RUN_ID}@example.com"
request POST "/users" "$SU_TOKEN" "{\"name\":\"Jane Smith\",\"email\":\"${JANE_EMAIL}\",\"username\":\"janesmith-${RUN_ID}\",\"phone\":\"+8801711122233\",\"tenant_id\":\"${ORG_SLUG}\",\"role\":\"MEMBER\",\"attributes\":{\"department\":\"Engineering\",\"designation\":\"Developer\",\"location\":\"Dhaka\"}}" "201" "superuser creates jane directly into the org via POST /users"
JANE_ID="$(jf '.id')"

request POST "/users" "$SU_TOKEN" "{\"name\":\"Dup\",\"email\":\"${JANE_EMAIL}\",\"tenant_id\":\"${ORG_SLUG}\",\"role\":\"MEMBER\"}" "409" "creating a second user with jane's email is rejected"

request GET "/users/${JANE_ID}" "$SU_TOKEN" "" "200" "superuser reads jane back — same Common User Object shape as GET /users/me"

request POST "/organizations/${ORG_ID}/invitations" "$SU_TOKEN" "{\"email\":\"${BOB_EMAIL}\",\"role_code\":\"member\"}" "201" "superuser invites bob into the org"
ORG_INVITE_TOKEN="$(jf '.invitation_token')"

request GET "/organizations/${ORG_ID}/invitations" "$SU_TOKEN" "" "200" "superuser lists pending invitations"

if [[ -n "$ORG_INVITE_TOKEN" && "$ORG_INVITE_TOKEN" != "null" ]]; then
  request POST "/organizations/invitations/accept" "$BOB_TOKEN" "{\"token\":\"${ORG_INVITE_TOKEN}\"}" "200" "bob accepts the org invitation"
else
  note "invitation_token was null (DEBUG=false on the server) — skipping /organizations/invitations/accept. Set DEBUG=true to exercise it."
fi

request PATCH "/organizations/${ORG_ID}/members/${ALICE_ID}" "$SU_TOKEN" '{"role_code":"admin"}' "200" "superuser promotes alice to admin"

# ---------------------------------------------------------------------------
section "4. TENANTS (bootstrap API — superuser-only)"
# ---------------------------------------------------------------------------

TENANT_ID="tenant-${RUN_ID}"
TENANT_OWNER_EMAIL="tenant-owner-${RUN_ID}@example.com"

request POST "/tenants" "$SU_TOKEN" "{\"name\":\"Globex Corp\",\"tenant_id\":\"${TENANT_ID}\",\"owner_email\":\"${TENANT_OWNER_EMAIL}\"}" "201" "superuser bootstraps a new tenant + owner invite"
TENANT_INVITE_TOKEN="$(jf '.bootstrap.invite_token')"

if [[ -n "$TENANT_INVITE_TOKEN" && "$TENANT_INVITE_TOKEN" != "null" ]]; then
  request POST "/auth/accept-invite" "" "{\"invite_token\":\"${TENANT_INVITE_TOKEN}\",\"name\":\"Tenant Owner\",\"password\":\"${PASSWORD}\"}" "201" "tenant owner accepts bootstrap invite, sets password"

  request POST "/auth/login" "" "{\"email\":\"${TENANT_OWNER_EMAIL}\",\"password\":\"${PASSWORD}\",\"tenant_id\":\"${TENANT_ID}\"}" "200" "tenant owner logs in"
  TENANT_OWNER_TOKEN="$(jf '.access_token')"
else
  note "tenant bootstrap invite_token missing — skipping accept-invite/login for the tenant owner"
  TENANT_OWNER_TOKEN=""
fi

INVITEE_EMAIL="invitee-${RUN_ID}@example.com"
request POST "/tenants/${TENANT_ID}/invites" "$SU_TOKEN" "{\"email\":\"${INVITEE_EMAIL}\",\"role\":\"Member\"}" "201" "superuser invites a member into the tenant"

# ---------------------------------------------------------------------------
section "5. ADMIN (direct user provisioning into an existing tenant)"
# ---------------------------------------------------------------------------

ADMIN_PROVISIONED_EMAIL="provisioned-${RUN_ID}@example.com"
request POST "/admin/users" "$SU_TOKEN" "{\"email\":\"${ADMIN_PROVISIONED_EMAIL}\",\"name\":\"Provisioned Person\",\"tenant_id\":\"${TENANT_ID}\",\"role\":\"Member\"}" "201" "superuser directly provisions a user into the tenant"

# ---------------------------------------------------------------------------
section "6. ROLES & PERMISSIONS"
# ---------------------------------------------------------------------------

request POST "/roles/seed" "$SU_TOKEN" "" "200" "superuser seeds the default global roles"
GLOBAL_ROLE_ID="$(jf '.[] | select(.code=="guest") | .id')"

# GET/POST /roles now follow Role_API_Specification_Extended.md: tenant-scoped
# via tenant_id (slug) rather than organization_id, slug instead of code, and
# {message,role}/{role}/{total,page,page_size,roles} response envelopes.
request GET "/roles" "$SU_TOKEN" "" "403" "superuser with no tenant context can't list without ?tenant_id or being superuser-global"
request GET "/roles?tenant_id=${ORG_SLUG}" "$SU_TOKEN" "" "200" "list acme's roles (explicit tenant_id override)"

request POST "/roles" "$SU_TOKEN" "{\"name\":\"Custom Org Role ${RUN_ID}\",\"slug\":\"custom_role_${RUN_ID}\",\"tenant_id\":\"${ORG_SLUG}\"}" "201" "superuser creates an org-scoped custom role"
CUSTOM_ROLE_ID="$(jf '.role.id')"

request GET "/roles/${CUSTOM_ROLE_ID}" "$SU_TOKEN" "" "200" "get the custom role by id"

request PUT "/roles/${CUSTOM_ROLE_ID}" "$SU_TOKEN" '{"description":"Updated description"}' "200" "update the custom role"

request POST "/roles/${CUSTOM_ROLE_ID}/permissions" "$SU_TOKEN" '{"permissions":["organizations:read"]}' "200" "grant a permission to the custom role"

request GET "/roles/${CUSTOM_ROLE_ID}/permissions" "$SU_TOKEN" "" "200" "list the custom role's permissions"

request DELETE "/roles/${CUSTOM_ROLE_ID}/permissions" "$SU_TOKEN" '{"permissions":["organizations:read"]}' "200" "revoke that permission from the custom role (bulk by code)"

# /roles/{id}/assignments is the platform-wide user_roles table — a
# separate mechanism from org membership roles, and global-roles-only
# (organization_id IS NULL), hence GLOBAL_ROLE_ID rather than CUSTOM_ROLE_ID.
request POST "/roles/${GLOBAL_ROLE_ID}/assignments" "$SU_TOKEN" "{\"user_id\":\"${ALICE_ID}\"}" "201" "superuser assigns the global guest role to alice"

request GET "/roles/assignments/${ALICE_ID}" "$SU_TOKEN" "" "200" "list alice's role assignments"

request DELETE "/roles/${GLOBAL_ROLE_ID}/assignments/${ALICE_ID}" "$SU_TOKEN" "" "204" "revoke the global role from alice"

request DELETE "/roles/${CUSTOM_ROLE_ID}" "$SU_TOKEN" "" "200" "delete the custom role (cleanup)"

# ---------------------------------------------------------------------------
section "7. RESOURCES"
# ---------------------------------------------------------------------------

request POST "/resources" "$ALICE_TOKEN" '{"name":"quarterly-report.pdf","type":"document","tags":{"confidentiality":"high"},"is_public":false}' "201" "alice registers a resource"
RESOURCE_ID="$(jf '.id')"

request GET "/resources" "$ALICE_TOKEN" "" "200" "alice lists visible resources"

request GET "/resources/${RESOURCE_ID}" "$ALICE_TOKEN" "" "200" "alice reads her resource"

request PATCH "/resources/${RESOURCE_ID}" "$ALICE_TOKEN" '{"tags":{"confidentiality":"medium"}}' "200" "alice updates her resource's tags"

# ---------------------------------------------------------------------------
section "8. POLICIES (ABAC — superuser-only CRUD, evaluation is per-caller)"
# ---------------------------------------------------------------------------

request POST "/policies" "$SU_TOKEN" '{"name":"Allow doc read","effect":"allow","resource":"document","action":"read"}' "201" "superuser creates an ABAC policy"
POLICY_ID="$(jf '.id')"

request GET "/policies" "$SU_TOKEN" "" "200" "list policies"

request GET "/policies/${POLICY_ID}" "$SU_TOKEN" "" "200" "get the policy by id"

request PATCH "/policies/${POLICY_ID}" "$SU_TOKEN" '{"description":"Allows reading documents"}' "200" "update the policy"

request POST "/policies/evaluate" "$ALICE_TOKEN" '{"resource_type":"document","action":"read"}' "200" "alice evaluates her own access to document:read"

request DELETE "/policies/${POLICY_ID}" "$SU_TOKEN" "" "204" "delete the policy (cleanup)"

request DELETE "/resources/${RESOURCE_ID}" "$ALICE_TOKEN" "" "204" "alice deletes her resource (cleanup)"

# ---------------------------------------------------------------------------
section "9. AUTH lifecycle — MFA, refresh, switch-tenant, password reset, logout"
# ---------------------------------------------------------------------------

request POST "/auth/login" "" "{\"email\":\"${PW_EMAIL}\",\"password\":\"${PASSWORD}\"}" "200" "login pwuser"
PW_TOKEN="$(jf '.access_token')"

request POST "/auth/mfa/setup" "$PW_TOKEN" "" "200" "pwuser starts TOTP enrollment"
MFA_SECRET="$(jf '.secret')"

if [[ -n "$MFA_SECRET" && "$MFA_SECRET" != "null" ]]; then
  TOTP_CODE="$(totp_code "$MFA_SECRET")"
  request POST "/auth/mfa/confirm" "$PW_TOKEN" "{\"code\":\"${TOTP_CODE}\"}" "200" "pwuser confirms TOTP enrollment"

  request POST "/auth/login" "" "{\"email\":\"${PW_EMAIL}\",\"password\":\"${PASSWORD}\"}" "200" "pwuser logs in again (now MFA-gated)"
  MFA_CHALLENGE_TOKEN="$(jf '.mfa_challenge_token')"

  TOTP_CODE="$(totp_code "$MFA_SECRET")"
  request POST "/auth/mfa/login-verify" "" "{\"mfa_challenge_token\":\"${MFA_CHALLENGE_TOKEN}\",\"code\":\"${TOTP_CODE}\"}" "200" "pwuser redeems the MFA challenge for real tokens"
  PW_TOKEN="$(jf '.access_token')"

  TOTP_CODE="$(totp_code "$MFA_SECRET")"
  request POST "/auth/mfa/disable" "$PW_TOKEN" "{\"current_password\":\"${PASSWORD}\",\"code\":\"${TOTP_CODE}\"}" "204" "pwuser disables MFA (cleanup)"
else
  note "MFA secret missing — skipping confirm/login-verify/disable"
fi

request POST "/auth/refresh" "" "" "200" "alice refreshes her access token via the login cookie" --cookies

request POST "/auth/switch-tenant" "$ALICE_TOKEN" "{\"tenant_id\":\"${ORG_SLUG}\"}" "200" "alice switches her session into the acme org" --cookies

request POST "/auth/change-password" "$PW_TOKEN" "{\"current_password\":\"${PASSWORD}\",\"new_password\":\"NewPassword456!\"}" "204" "pwuser changes her password"

request POST "/auth/forgot-password" "" "{\"email\":\"${PW_EMAIL}\"}" "200" "pwuser requests a password reset"
RESET_TOKEN="$(jf '.reset_token')"

if [[ -n "$RESET_TOKEN" && "$RESET_TOKEN" != "null" ]]; then
  request POST "/auth/reset-password" "" "{\"token\":\"${RESET_TOKEN}\",\"new_password\":\"AnotherPassword789!\"}" "204" "pwuser resets her password using the reset token"
else
  note "reset_token was null (DEBUG=false on the server) — skipping /auth/reset-password. Set DEBUG=true to exercise it."
fi

request GET "/auth/google/login" "" "" "200" "fetch the Google OAuth consent URL (callback requires a real browser flow — not exercised here)"

request POST "/auth/logout" "$ALICE_TOKEN" "" "204" "alice logs out" --cookies

# ---------------------------------------------------------------------------
section "10. TENANT GROUPS (Organization<->Tenant many-to-many — superuser-only, distinct from section 4's /tenants bootstrap API)"
# ---------------------------------------------------------------------------

TENANT_GROUP_SLUG="tenant-group-${RUN_ID}"

request POST "/tenant-groups" "$SU_TOKEN" "{\"name\":\"Acme Holding\",\"slug\":\"${TENANT_GROUP_SLUG}\"}" "201" "superuser creates a tenant group"
TENANT_GROUP_ID="$(jf '.id')"

request GET "/tenant-groups" "$SU_TOKEN" "" "200" "superuser lists tenant groups"

request GET "/tenant-groups/${TENANT_GROUP_ID}" "$SU_TOKEN" "" "200" "superuser reads the tenant group"

request PATCH "/tenant-groups/${TENANT_GROUP_ID}" "$SU_TOKEN" '{"name":"Acme Holding Co"}' "200" "superuser renames the tenant group"

# Re-links the "acme" organization created in section 3 — an organization
# can belong to several tenant groups, and a tenant group can hold several
# organizations.
request POST "/tenant-groups/${TENANT_GROUP_ID}/organizations" "$SU_TOKEN" "{\"organization_id\":\"${ORG_ID}\"}" "201" "superuser links the acme org into the tenant group"

request GET "/tenant-groups/${TENANT_GROUP_ID}/organizations" "$SU_TOKEN" "" "200" "list organizations linked to the tenant group"

request GET "/tenant-groups/by-organization/${ORG_ID}" "$SU_TOKEN" "" "200" "list tenant groups the acme org belongs to"

request POST "/tenant-groups/${TENANT_GROUP_ID}/organizations" "$SU_TOKEN" "{\"organization_id\":\"${ORG_ID}\"}" "409" "linking the same org twice is rejected"

request DELETE "/tenant-groups/${TENANT_GROUP_ID}/organizations/${ORG_ID}" "$SU_TOKEN" "" "204" "superuser unlinks the acme org"

request DELETE "/tenant-groups/${TENANT_GROUP_ID}" "$SU_TOKEN" "" "204" "superuser deletes the tenant group (cleanup)"

# ---------------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------------

printf "${GREEN}%d passed${RESET}, ${RED}%d failed${RESET}\n" "$PASS_COUNT" "$FAIL_COUNT"
printf "Run artifacts (for manual inspection/cleanup): org slug=%s tenant id=%s alice=%s bob=%s pwuser=%s\n" \
  "$ORG_SLUG" "$TENANT_ID" "$ALICE_EMAIL" "$BOB_EMAIL" "$PW_EMAIL"
printf "To provision the persistent named 'Apple Corp' demo tenant (scripts/dummy.json), run scripts/seed.sh instead.\n"

[[ "$FAIL_COUNT" -eq 0 ]]
