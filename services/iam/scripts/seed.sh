#!/usr/bin/env bash
# Provisions the "Apple Corp" demo tenant (scripts/dummy.json) as real,
# persistent data on a running instance of this service — every user's
# password is Hello123. Unlike scripts/api.sh (a disposable smoke test that
# cleans up after itself), this script leaves everything it creates in
# place: it's meant to seed a tenant you can actually log into and explore
# afterward, on localhost or a real deployment.
#
# Requires an existing superuser to call the superuser-only provisioning
# endpoints (organizations/tenants/roles/policies) — see
# scripts/create_superuser.py if you don't have one yet:
#   uv run python scripts/create_superuser.py <email> <password>
#
# Usage:
#   ./scripts/seed.sh
#   BASE_URL=https://nutratenant-iam-latest.onrender.com \
#     SUPERUSER_EMAIL=diptunazmulalam@gmail.com SUPERUSER_PASSWORD=Hello123 \
#     ./scripts/seed.sh
#
# Idempotency: tenant_id "apple-corp" and every @apple-corp.com email are
# literal, not suffixed — this seeds one specific named tenant, not a fresh
# disposable instance every run. If it already exists, POST /tenants 409s
# and the script stops there: there's no GET-organization-by-slug endpoint
# this API exposes to a superuser who isn't already a member, so there's no
# reliable way to fetch the existing org id and resume from there.

set -uo pipefail

command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required (brew install jq)" >&2; exit 1; }

BASE_URL="${BASE_URL:-http://localhost:8000}"
API="${BASE_URL}/api/v1"
SUPERUSER_EMAIL="${SUPERUSER_EMAIL:-diptunazmulalam@gmail.com}"
SUPERUSER_PASSWORD="${SUPERUSER_PASSWORD:-Hello123}"
APPLE_PASSWORD="Hello123"
APPLE_TENANT_ID="apple-corp"
APPLE_OWNER_EMAIL="john.ceo@apple-corp.com"

BOLD=$'\033[1m'; RESET=$'\033[0m'; GREEN=$'\033[32m'; RED=$'\033[31m'; CYAN=$'\033[36m'; YELLOW=$'\033[33m'

PASS_COUNT=0
FAIL_COUNT=0

section() {
  printf "\n${BOLD}${CYAN}========== %s ==========${RESET}\n" "$1"
}

note() {
  printf "${YELLOW}NOTE:${RESET} %s\n" "$1"
}

# request METHOD PATH TOKEN DATA EXPECTED_STATUS LABEL
# Sets globals RESP_BODY / RESP_STATUS for the caller to inspect afterward.
request() {
  local method="$1" path="$2" token="$3" data="$4" expected="$5" label="$6"
  local url="${API}${path}"
  local -a curl_args=(-sS -X "$method" "$url" -H "Content-Type: application/json")
  [[ -n "$token" ]] && curl_args+=(-H "Authorization: Bearer ${token}")
  [[ -n "$data" ]] && curl_args+=(-d "$data")

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
section "Preflight"
# ---------------------------------------------------------------------------

HEALTH_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}/health")"
if [[ "$HEALTH_STATUS" == "200" ]]; then
  printf "${GREEN}PASS${RESET} [200] GET    /health -> service reachable at %s\n" "$BASE_URL"
else
  printf "${RED}FAIL${RESET} [%s] GET    /health -> is %s reachable?\n" "$HEALTH_STATUS" "$BASE_URL"
fi

request POST "/auth/login" "" "{\"email\":\"${SUPERUSER_EMAIL}\",\"password\":\"${SUPERUSER_PASSWORD}\"}" "200" "login superuser"
SU_TOKEN="$(jf '.access_token')"
if [[ -z "$SU_TOKEN" || "$SU_TOKEN" == "null" ]]; then
  note "No superuser session — every step below will fail. Create one with scripts/create_superuser.py first."
fi

# ---------------------------------------------------------------------------
section "Tenant — Apple Corp"
# ---------------------------------------------------------------------------

request POST "/tenants" "$SU_TOKEN" "{\"name\":\"Apple Corp\",\"tenant_id\":\"${APPLE_TENANT_ID}\",\"owner_email\":\"${APPLE_OWNER_EMAIL}\",\"plan\":\"enterprise\"}" "201" "superuser bootstraps the Apple Corp tenant"

if [[ "$RESP_STATUS" == "409" ]]; then
  note "Tenant '${APPLE_TENANT_ID}' already exists — nothing more this script can safely do (no get-org-by-slug endpoint to resume from). Exiting."
  exit 0
elif [[ "$RESP_STATUS" != "201" ]]; then
  note "Tenant creation failed unexpectedly — stopping rather than cascading failures through the rest of the seed."
  exit 1
fi

APPLE_ORG_ID="$(jf '.tenant.id')"
APPLE_OWNER_INVITE_TOKEN="$(jf '.bootstrap.invite_token')"

if [[ -n "$APPLE_OWNER_INVITE_TOKEN" && "$APPLE_OWNER_INVITE_TOKEN" != "null" ]]; then
  request POST "/auth/accept-invite" "" "{\"invite_token\":\"${APPLE_OWNER_INVITE_TOKEN}\",\"name\":\"John Smith\",\"password\":\"${APPLE_PASSWORD}\"}" "201" "John (owner) accepts the bootstrap invite"
  APPLE_OWNER_ID="$(jf '.user_id')"

  request PATCH "/users/${APPLE_OWNER_ID}/attributes" "$SU_TOKEN" '{"attributes":{"department":"Executive","job_title":"CEO","role":"owner","clearance_level":5,"employment_type":"full_time","location":"USA"}}' "200" "set John's ABAC attributes"
else
  note "Owner invite_token missing from the tenant-creation response — skipping owner accept-invite/attributes."
fi

# Custom org-scoped role — "moderator" isn't one of the four roles every
# org is auto-provisioned with (owner/admin/member/viewer, see
# app.modules.roles.service.DEFAULT_ORG_ROLES), so dummy.json's
# moderator-tier users need it created before they can be added as members.
request POST "/roles" "$SU_TOKEN" "{\"name\":\"Moderator\",\"slug\":\"moderator\",\"tenant_id\":\"${APPLE_TENANT_ID}\"}" "201" "create the org-scoped 'moderator' role"

# ---------------------------------------------------------------------------
section "Tenant Group — Apple Holdings (Organization<->Tenant many-to-many demo)"
# ---------------------------------------------------------------------------

# Distinct from the "Apple Corp" tenant_id/org above: this is the new,
# separate Tenant entity an Organization can belong to several of — see
# app/services/tenant_service.py. Best-effort: on a repeat run against an
# already-seeded apple-corp, this 409s and the link step below is skipped.
request POST "/tenant-groups" "$SU_TOKEN" '{"name":"Apple Holdings","slug":"apple-holdings"}' "201" "superuser creates the Apple Holdings tenant group"
APPLE_TENANT_GROUP_ID="$(jf '.id')"

if [[ -n "$APPLE_TENANT_GROUP_ID" && "$APPLE_TENANT_GROUP_ID" != "null" ]]; then
  request POST "/tenant-groups/${APPLE_TENANT_GROUP_ID}/organizations" "$SU_TOKEN" "{\"organization_id\":\"${APPLE_ORG_ID}\"}" "201" "link the apple-corp org into Apple Holdings"
else
  note "Tenant group 'apple-holdings' already exists (or creation failed) — skipping the organization link."
fi

# ---------------------------------------------------------------------------
section "Staff"
# ---------------------------------------------------------------------------

# email|first|last|department|job_title|role_code|clearance_level|employment_type|location
APPLE_STAFF="sarah.admin@apple-corp.com|Sarah|Johnson|IT|IT Director|admin|4|full_time|USA
michael.admin@apple-corp.com|Michael|Brown|Operations|Operations Manager|admin|4|full_time|USA
emma.mod@apple-corp.com|Emma|Wilson|HR|HR Manager|moderator|3|full_time|USA
david.mod@apple-corp.com|David|Taylor|Finance|Finance Lead|moderator|3|full_time|USA
alice@apple-corp.com|Alice|Miller|Engineering|Software Engineer|member|2|full_time|USA
bob@apple-corp.com|Bob|Davis|Engineering|Backend Engineer|member|2|full_time|USA
charlie@apple-corp.com|Charlie|Anderson|Design|UX Designer|member|2|full_time|USA
diana@apple-corp.com|Diana|Thomas|Marketing|Marketing Specialist|member|2|full_time|USA
ethan@apple-corp.com|Ethan|Moore|Sales|Sales Executive|member|2|full_time|USA"

while IFS='|' read -r email first last dept title role_code clearance emp_type location; do
  [[ -z "${email}" ]] && continue
  full_name="${first} ${last}"

  request POST "/auth/register" "" "{\"email\":\"${email}\",\"password\":\"${APPLE_PASSWORD}\",\"full_name\":\"${full_name}\"}" "201" "register ${full_name} (${role_code})"
  staff_id="$(jf '.id')"

  request POST "/organizations/${APPLE_ORG_ID}/members" "$SU_TOKEN" "{\"user_id\":\"${staff_id}\",\"role_code\":\"${role_code}\"}" "201" "add ${full_name} to apple-corp as ${role_code}"

  request PATCH "/users/${staff_id}/attributes" "$SU_TOKEN" "{\"attributes\":{\"department\":\"${dept}\",\"job_title\":\"${title}\",\"role\":\"${role_code}\",\"clearance_level\":${clearance},\"employment_type\":\"${emp_type}\",\"location\":\"${location}\"}}" "200" "set ${full_name}'s ABAC attributes"
done <<< "${APPLE_STAFF}"

# ---------------------------------------------------------------------------
section "Resources"
# ---------------------------------------------------------------------------

# created_by is always the authenticated caller (no arbitrary owner_user_id
# field on this API), so each resource is registered by logging in as the
# specific person dummy.json names as its owner.
request POST "/auth/login" "" "{\"email\":\"sarah.admin@apple-corp.com\",\"password\":\"${APPLE_PASSWORD}\"}" "200" "login Sarah (for resource ownership)"
SARAH_TOKEN="$(jf '.access_token')"
request POST "/resources" "$SARAH_TOKEN" '{"name":"System Architecture","type":"document","tags":{"department":"Engineering","classification":"restricted"}}' "201" "Sarah registers the System Architecture doc"

request POST "/auth/login" "" "{\"email\":\"emma.mod@apple-corp.com\",\"password\":\"${APPLE_PASSWORD}\"}" "200" "login Emma (for resource ownership)"
EMMA_TOKEN="$(jf '.access_token')"
request POST "/resources" "$EMMA_TOKEN" '{"name":"Employee Handbook","type":"document","tags":{"department":"HR","classification":"internal"}}' "201" "Emma registers the Employee Handbook"

request POST "/auth/login" "" "{\"email\":\"david.mod@apple-corp.com\",\"password\":\"${APPLE_PASSWORD}\"}" "200" "login David (for resource ownership)"
DAVID_TOKEN="$(jf '.access_token')"
request POST "/resources" "$DAVID_TOKEN" '{"name":"Payroll Report 2026","type":"document","tags":{"department":"Finance","classification":"confidential"}}' "201" "David registers the Payroll Report"

request POST "/auth/login" "" "{\"email\":\"alice@apple-corp.com\",\"password\":\"${APPLE_PASSWORD}\"}" "200" "login Alice (for resource ownership)"
APPLE_ALICE_TOKEN="$(jf '.access_token')"
request POST "/resources" "$APPLE_ALICE_TOKEN" '{"name":"Mobile Banking App","type":"project","tags":{"department":"Engineering","classification":"internal"}}' "201" "Alice registers the Mobile Banking App project"

# ---------------------------------------------------------------------------
section "ABAC Policies"
# ---------------------------------------------------------------------------

# PolicyCreateRequest is one (resource, action) pair per row; dummy.json's
# multi-action policies (e.g. moderator's [read, update, approve]) are
# collapsed to their primary action here. Conditions use this service's
# real DSL (app/domain/policy_conditions.py), not dummy.json's pseudo
# "user.x: resource.y" shorthand. "role" is folded into each user's ABAC
# attributes bag above specifically so these conditions can reference it —
# the PDP's evaluation context only ever sees subject.attributes.*, never a
# user's org-membership role_code.
request POST "/policies" "$SU_TOKEN" '{"name":"Department Resource Read","effect":"allow","resource":"document","action":"read","conditions":{"op":"eq","left":{"var":"subject.attributes.department"},"right":{"var":"resource.department"}}}' "201" "create policy: same-department read"

request POST "/policies" "$SU_TOKEN" '{"name":"Moderator Department Access","effect":"allow","resource":"document","action":"update","conditions":{"all":[{"op":"eq","left":{"var":"subject.attributes.role"},"right":"moderator"},{"op":"eq","left":{"var":"subject.attributes.department"},"right":{"var":"resource.department"}}]}}' "201" "create policy: moderator manages own department"

request POST "/policies" "$SU_TOKEN" '{"name":"Admin Tenant Management","effect":"allow","resource":"document","action":"update","conditions":{"op":"eq","left":{"var":"subject.attributes.role"},"right":"admin"}}' "201" "create policy: admin manages tenant documents"

request POST "/policies" "$SU_TOKEN" '{"name":"Owner Full Access","effect":"allow","resource":"*","action":"*","conditions":{"op":"eq","left":{"var":"subject.attributes.role"},"right":"owner"}}' "201" "create policy: owner unrestricted access"

# Replays dummy.json's authorization_requests[0] verbatim: Alice (member,
# Engineering) reading the restricted System Architecture doc (department
# Engineering) — expected to match "Department Resource Read" and allow.
request POST "/policies/evaluate" "$APPLE_ALICE_TOKEN" '{"resource_type":"document","action":"read","resource_attributes":{"department":"Engineering","classification":"restricted"}}' "200" "Alice evaluates read access to an Engineering doc (expect allow)"
EVAL_DECISION="$(jf '.decision')"
if [[ "$EVAL_DECISION" == "allow" ]]; then
  note "Evaluation result matches dummy.json's authorization_requests[0] (decision=allow, matched_policy=pol_member_department_read)."
else
  note "UNEXPECTED — dummy.json's equivalent request decides 'allow', got '${EVAL_DECISION}'."
fi

# ---------------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------------

printf "${GREEN}%d passed${RESET}, ${RED}%d failed${RESET}\n" "$PASS_COUNT" "$FAIL_COUNT"
printf "Apple Corp tenant seeded on %s — tenant_id=%s, password '%s' for every user:\n" "$BASE_URL" "$APPLE_TENANT_ID" "$APPLE_PASSWORD"
printf "  %s (owner)\n" "$APPLE_OWNER_EMAIL"
printf "  sarah.admin@apple-corp.com / michael.admin@apple-corp.com (admin)\n"
printf "  emma.mod@apple-corp.com / david.mod@apple-corp.com (moderator)\n"
printf "  alice@apple-corp.com / bob@apple-corp.com / charlie@apple-corp.com / diana@apple-corp.com / ethan@apple-corp.com (member)\n"

[[ "$FAIL_COUNT" -eq 0 ]]
