#!/usr/bin/env bash
# Helm values update script for DevOps repository
# Updates image tags in devops-k8s repository and pushes changes

set -euo pipefail

log_info() { echo -e "\033[0;34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[0;32m[SUCCESS]\033[0m $1"; }
log_warning() { echo -e "\033[1;33m[WARNING]\033[0m $1"; }
log_error() { echo -e "\033[0;31m[ERROR]\033[0m $1"; }
log_step() { echo -e "\033[0;35m[STEP]\033[0m $1"; }

# Required variables
APP_NAME=${APP_NAME:-erp-api}
IMAGE_REPO=${IMAGE_REPO:-}
GIT_COMMIT_ID=${GIT_COMMIT_ID:-}
DEVOPS_REPO=${DEVOPS_REPO:-Bengo-Hub/devops-k8s}
DEVOPS_DIR=${DEVOPS_DIR:-"$HOME/devops-k8s"}
VALUES_FILE_PATH=${VALUES_FILE_PATH:-apps/erp-api/values.yaml}
GIT_USER=${GIT_USER:-"Titus Owuor"}
GIT_EMAIL=${GIT_EMAIL:-"titusowuor30@gmail.com"}
REGISTRY_USERNAME=${REGISTRY_USERNAME:-}
REGISTRY_PASSWORD=${REGISTRY_PASSWORD:-}

if [[ -z "$IMAGE_REPO" || -z "$GIT_COMMIT_ID" ]]; then
    log_error "IMAGE_REPO and GIT_COMMIT_ID are required"
    exit 1
fi

log_step "Updating Helm values..."

# Clone or update devops-k8s repo into DEVOPS_DIR using token when available
TOKEN="${GH_PAT:-${GITHUB_SECRET:-${GITHUB_TOKEN:-}}}"
ORIGIN_REPO="${GITHUB_REPOSITORY:-}"

# Debug: log which token source is being used (without revealing value)
if [[ -n "${GH_PAT:-}" ]]; then
    log_info "Using GH_PAT for git operations"
elif [[ -n "${GITHUB_SECRET:-}" ]]; then
    log_info "Using GITHUB_SECRET for git operations"
elif [[ -n "${GITHUB_TOKEN:-}" ]]; then
    log_info "Using GITHUB_TOKEN for git operations (may lack cross-repo write)"
else
    log_warning "No GitHub token found"
fi

# For cross-repo pushes, we REQUIRE a PAT (deploy keys and GITHUB_TOKEN don't work)
if [[ -n "$ORIGIN_REPO" && "$DEVOPS_REPO" != "$ORIGIN_REPO" ]]; then
    if [[ -z "${GH_PAT:-${GITHUB_SECRET:-}}" ]]; then
        log_error "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log_error "CRITICAL: GH_PAT or GITHUB_SECRET required for cross-repo push"
        log_error "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log_error "You are pushing from: ${ORIGIN_REPO}"
        log_error "         to repository: ${DEVOPS_REPO}"
        log_error ""
        log_error "Default GITHUB_TOKEN does NOT have cross-repo write access."
        log_error "Deploy keys also do NOT work for pushing to other repos."
        log_error ""
        log_error "ACTION REQUIRED:"
        log_error "1. Create a Personal Access Token (PAT) at:"
        log_error "   https://github.com/settings/tokens/new"
        log_error "2. Select scope: 'repo' (full control)"
        log_error "3. Add as repository secret named 'GH_PAT' or 'GITHUB_SECRET'"
        log_error "4. Re-run this workflow"
        log_error "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        exit 1
    fi
fi

CLONE_URL="https://github.com/${DEVOPS_REPO}.git"
[[ -n "$TOKEN" ]] && CLONE_URL="https://x-access-token:${TOKEN}@github.com/${DEVOPS_REPO}.git"

if [[ ! -d "$DEVOPS_DIR" ]]; then
    log_info "Cloning devops repo into $DEVOPS_DIR"
    git clone "$CLONE_URL" "$DEVOPS_DIR" || { log_error "Failed to clone devops-k8s"; exit 1; }
fi

if [[ -d "$DEVOPS_DIR" ]]; then
    cd "$DEVOPS_DIR"
    git config user.name "$GIT_USER"
    git config user.email "$GIT_EMAIL"

    git fetch origin main || true
    git checkout main || git checkout -b main

    if [[ -f "$VALUES_FILE_PATH" ]]; then
        IMAGE_REPO_ENV="$IMAGE_REPO" IMAGE_TAG_ENV="$GIT_COMMIT_ID" \
        yq e -i '.image.repository = env(IMAGE_REPO_ENV) | .image.tag = env(IMAGE_TAG_ENV)' "$VALUES_FILE_PATH"
        if [[ -n "${REGISTRY_USERNAME:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
            yq e -i '.image.pullSecrets = [{"name":"registry-credentials"}]' "$VALUES_FILE_PATH"
        fi
        git add "$VALUES_FILE_PATH"
        git commit -m "${APP_NAME}:${GIT_COMMIT_ID} released" || echo "No changes to commit"
        git pull --rebase origin main || true
        if [[ -z "$TOKEN" ]]; then
            log_error "No GitHub token (GH_PAT/GITHUB_TOKEN/GITHUB_SECRET) available for devops-k8s push"
            log_warning "Skipping git push; set GH_PAT (preferred) with repo write perms to Bengo-Hub/devops-k8s"
        else
            if git remote | grep -q push-origin; then git remote remove push-origin || true; fi
            git remote add push-origin "https://x-access-token:${TOKEN}@github.com/${DEVOPS_REPO}.git"
            git push push-origin HEAD:main || log_warning "Git push failed"
        fi
    fi
    cd - >/dev/null 2>&1 || true
    log_success "Helm values updated"
fi

