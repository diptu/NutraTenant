#!/usr/bin/env bash
# Builds, double-tags, and pushes the NutraTenant IAM service image to Docker Hub.
#
# Usage:
#   ./scripts/deploy.sh
#
# Version tag = the current git commit's short SHA (immutable, traceable to
# an exact commit, no manual version bumping required). If the working tree
# has uncommitted changes, "-dirty" is appended so a dirty build can never be
# mistaken for the actual commit it was built from.

set -euo pipefail

# ---------------------------------------------------------------------------
# Explicit configuration — no placeholders.
# ---------------------------------------------------------------------------
DOCKERHUB_USERNAME="diptu"
IMAGE_NAME="nutratenant-iam"
FULL_IMAGE="${DOCKERHUB_USERNAME}/${IMAGE_NAME}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_CONTEXT="$(cd "${SCRIPT_DIR}/.." && pwd)"   # services/iam
DOCKERFILE="${BUILD_CONTEXT}/Dockerfile"
PLATFORM="linux/amd64"

DOCKER_CONFIG_FILE="${DOCKER_CONFIG:-${HOME}/.docker}/config.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
COLOR_RESET=$'\033[0m'
COLOR_BLUE=$'\033[34m'
COLOR_GREEN=$'\033[32m'
COLOR_YELLOW=$'\033[33m'
COLOR_RED=$'\033[31m'

log_info()    { printf "%s[INFO]%s  %s\n"  "${COLOR_BLUE}"   "${COLOR_RESET}" "$1"; }
log_success() { printf "%s[OK]%s    %s\n" "${COLOR_GREEN}"  "${COLOR_RESET}" "$1"; }
log_warn()    { printf "%s[WARN]%s  %s\n"  "${COLOR_YELLOW}" "${COLOR_RESET}" "$1"; }
log_error()   { printf "%s[ERROR]%s %s\n" "${COLOR_RED}"    "${COLOR_RESET}" "$1" >&2; }

trap 'log_error "deploy.sh failed at line ${LINENO} (last command: ${BASH_COMMAND})"' ERR

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
log_info "Checking prerequisites..."

command -v docker >/dev/null 2>&1 || { log_error "docker is required but not installed."; exit 1; }
docker info >/dev/null 2>&1 || { log_error "Docker daemon is not running. Start Docker and retry."; exit 1; }
command -v git >/dev/null 2>&1 || { log_error "git is required but not installed."; exit 1; }

if ! git -C "${BUILD_CONTEXT}" rev-parse --git-dir >/dev/null 2>&1; then
  log_error "${BUILD_CONTEXT} is not inside a git repository — cannot derive a version tag."
  exit 1
fi

[[ -f "${DOCKERFILE}" ]] || { log_error "Dockerfile not found at ${DOCKERFILE}"; exit 1; }

log_success "Prerequisites satisfied."

# ---------------------------------------------------------------------------
# Version tag: short git SHA, "-dirty" suffix if the tree has local changes.
# ---------------------------------------------------------------------------
GIT_SHA="$(git -C "${BUILD_CONTEXT}" rev-parse --short=12 HEAD)"
if [[ -n "$(git -C "${BUILD_CONTEXT}" status --porcelain)" ]]; then
  VERSION_TAG="${GIT_SHA}-dirty"
  log_warn "Working tree has uncommitted changes — tagging as '${VERSION_TAG}'."
else
  VERSION_TAG="${GIT_SHA}"
fi

log_info "Image:        ${FULL_IMAGE}"
log_info "Version tag:  ${VERSION_TAG}"
log_info "Latest tag:   latest"
log_info "Platform:     ${PLATFORM}"
log_info "Build context: ${BUILD_CONTEXT}"

# ---------------------------------------------------------------------------
# Docker Hub authentication — best-effort check, interactive fallback.
# ---------------------------------------------------------------------------
has_dockerhub_session() {
  [[ -f "${DOCKER_CONFIG_FILE}" ]] && grep -q "index.docker.io" "${DOCKER_CONFIG_FILE}" 2>/dev/null
}

if has_dockerhub_session; then
  log_success "Existing Docker Hub session detected in ${DOCKER_CONFIG_FILE}."
else
  log_warn "No active Docker Hub session detected — falling back to interactive login."
  docker login --username "${DOCKERHUB_USERNAME}"
fi

# ---------------------------------------------------------------------------
# Build — single build, two tags (specific version + latest).
# ---------------------------------------------------------------------------
log_info "Building ${FULL_IMAGE}:${VERSION_TAG} and ${FULL_IMAGE}:latest..."

docker build \
  --platform "${PLATFORM}" \
  -f "${DOCKERFILE}" \
  -t "${FULL_IMAGE}:${VERSION_TAG}" \
  -t "${FULL_IMAGE}:latest" \
  "${BUILD_CONTEXT}"

log_success "Build complete."

# ---------------------------------------------------------------------------
# Push — both tags. A credential-helper-based login (e.g. osxkeychain) won't
# always show up in config.json's "auths" key even when valid, so a push
# failing for auth reasons gets exactly one interactive-login retry rather
# than failing the whole deploy outright.
# ---------------------------------------------------------------------------
push_tag() {
  local tag="$1"
  log_info "Pushing ${tag}..."
  if ! docker push "${tag}" 2>/tmp/deploy_push_err.$$; then
    if grep -qi "denied\|unauthorized\|authentication required" /tmp/deploy_push_err.$$; then
      rm -f /tmp/deploy_push_err.$$
      log_warn "Push rejected as unauthenticated — retrying after interactive login."
      docker login --username "${DOCKERHUB_USERNAME}"
      docker push "${tag}"
    else
      cat /tmp/deploy_push_err.$$ >&2
      rm -f /tmp/deploy_push_err.$$
      return 1
    fi
  fi
  rm -f /tmp/deploy_push_err.$$
  log_success "Pushed ${tag}."
}

push_tag "${FULL_IMAGE}:${VERSION_TAG}"
push_tag "${FULL_IMAGE}:latest"

# ---------------------------------------------------------------------------
log_success "Deploy complete."
log_info "  https://hub.docker.com/r/${DOCKERHUB_USERNAME}/${IMAGE_NAME}/tags"
log_info "  docker pull ${FULL_IMAGE}:${VERSION_TAG}"
log_info "  docker pull ${FULL_IMAGE}:latest"
