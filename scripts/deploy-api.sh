#!/usr/bin/env bash
# LEAD ONLY. Deploy the API (origin/main) to the lead's server over SSH, then health-check it.
# Agents must not run this (AGENTS.md: only leads deploy). See docs/DEPLOY.md.
#
#   FAULTLINE_DEPLOY_SSH=<ssh-target> scripts/deploy-api.sh
#   scripts/deploy-api.sh <ssh-target>            # or: make deploy-api SSH=<ssh-target>
#
# <ssh-target> is anything `ssh` accepts; use a Host alias from your ~/.ssh/config. It is never committed.
# Optional env:
#   FAULTLINE_DEPLOY_DIR  path of the repo clone on the server (default: faultline, relative to the remote home)
#   FAULTLINE_API_HOST    public API host for the final check (default: read from the server's deploy/.env)
set -euo pipefail

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

case "${1:-}" in -h | --help) usage ;; esac
target="${1:-${FAULTLINE_DEPLOY_SSH:-}}"
[ -n "$target" ] || usage
case "$target" in -*) echo "refusing an ssh target that starts with '-'" >&2; exit 2 ;; esac
remote_dir="${FAULTLINE_DEPLOY_DIR:-faultline}"

# The remote half runs on the server via `bash -s`. Kept in a variable (not a heredoc inside $(...)) so the
# script parses the same on macOS's bash 3.2.
read -r -d '' REMOTE_SCRIPT <<'REMOTE' || true
set -euo pipefail
dir="$1"
case "$dir" in "~/"*) dir="$HOME/${dir#\~/}" ;; esac
cd "$dir"
[ -f deploy/.env ] || { echo "deploy/.env missing on the server (copy deploy/.env.example, see docs/DEPLOY.md)" >&2; exit 1; }
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "server checkout has local changes; refusing to deploy" >&2; exit 1
fi
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = main ] || { echo "server checkout is on '$branch', expected main (git switch main)" >&2; exit 1; }

prev="$(git rev-parse --short HEAD)"
git pull --ff-only origin main >&2
now="$(git rev-parse --short HEAD)"
echo "commit $prev -> $now" >&2

compose="docker compose -f deploy/docker-compose.yml"
$compose up -d --build --remove-orphans >&2

status=unknown
for _ in $(seq 1 45); do
  cid="$($compose ps -q api)"
  status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo unknown)"
  [ "$status" = healthy ] && break
  sleep 2
done
if [ "$status" != healthy ]; then
  $compose logs --tail 60 api >&2
  echo "api container is '$status'. Roll back: git checkout $prev && $compose up -d --build" >&2
  exit 1
fi
echo "api container healthy" >&2
echo "ROLLBACK_TO=$prev"
echo "API_HOST=$(sed -n 's/^FAULTLINE_API_HOST=//p' deploy/.env | tail -n 1 | tr -d '\r"'"'"' ')"
REMOTE

echo "==> deploying origin/main on the server (target from your environment, not printed)"
# ssh joins its arguments into one string for the remote shell, so the directory is shell-quoted here.
remote_cmd="bash -s -- $(printf '%q' "$remote_dir")"
remote_out="$(printf '%s\n' "$REMOTE_SCRIPT" | ssh -o BatchMode=yes "$target" "$remote_cmd")"

rollback_to="$(printf '%s\n' "$remote_out" | sed -n 's/^ROLLBACK_TO=//p')"
api_host="${FAULTLINE_API_HOST:-$(printf '%s\n' "$remote_out" | sed -n 's/^API_HOST=//p')}"
[ -n "$api_host" ] || { echo "could not determine FAULTLINE_API_HOST for the public check" >&2; exit 1; }

echo "==> public health check: https://$api_host/api/health"
headers=""
for _ in $(seq 1 20); do
  # First deploy: Caddy may still be obtaining the certificate.
  if headers="$(curl -fsS --max-time 10 -D - -o /dev/null "https://$api_host/api/health" 2>/dev/null)"; then
    break
  fi
  headers=""
  sleep 3
done
if [ -z "$headers" ]; then
  echo "public health check FAILED. Previous server commit: $rollback_to (docs/DEPLOY.md, Rollback)" >&2
  exit 1
fi
mode="$(printf '%s\n' "$headers" | tr -d '\r' | sed -n 's/^[Xx]-[Ff]aultline-[Mm]ode: *//p')"
if [ "$mode" != public ]; then
  echo "API answered but reports mode '${mode:-NOT AVAILABLE}', expected 'public'" >&2
  exit 1
fi
echo "OK: https://$api_host is up in public mode. Previous server commit: $rollback_to"
