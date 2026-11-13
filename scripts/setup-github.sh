#!/usr/bin/env bash
# One-time (idempotent) GitHub setup for FAULTLINE. Run by a LEAD (repo admin), by hand, not by an agent:
#   bash scripts/setup-github.sh
# Creates labels and a ruleset on the default branch so that:
#   - nobody but repo admins can update `main` (only admins merge PRs or push)
#   - PRs need 1 approval incl. code owner (shown on the PR), stale approvals are dismissed
#   - CI job `checks` must pass, no force pushes, no branch deletion
#   - optional `production` environment that requires a lead to approve deployments
set -euo pipefail
REPO="${REPO:-LavishSphere/faultline}"
LEAD="${LEAD:-LavishSphere}"

echo "== labels"
label() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force >/dev/null && echo "  $1"; }
label delegated   "F5A524" "Task assigned by a lead; partner agents may only work on these"
label ws:backend  "19D3C5" "API, providers, infra"
label ws:replay   "19D3C5" "Temporal gate, sealed outcomes, provenance"
label ws:eval     "19D3C5" "Scoring and benchmark"
label ws:finance  "19D3C5" "Financial model and optimizer"
label ws:markets  "19D3C5" "Kalshi/Polymarket data"
label ws:frontend "19D3C5" "Web app and visuals"
label ws:research "19D3C5" "VC research lenses"

echo "== ruleset: protect-main"
RULESET=$(cat <<'JSON'
{
  "name": "protect-main",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [ { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" } ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "update", "parameters": { "update_allows_fetch_and_merge": false } },
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": true,
        "require_last_push_approval": true,
        "required_review_thread_resolution": false } },
    { "type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [ { "context": "checks" } ] } }
  ]
}
JSON
)
EXISTING=$(gh api "repos/$REPO/rulesets" --jq '.[] | select(.name=="protect-main") | .id' || true)
if [ -n "$EXISTING" ]; then
  echo "$RULESET" | gh api -X PUT "repos/$REPO/rulesets/$EXISTING" --input - >/dev/null && echo "  updated ruleset $EXISTING"
else
  echo "$RULESET" | gh api -X POST "repos/$REPO/rulesets" --input - >/dev/null && echo "  created ruleset"
fi

echo "== environment: production (deploys need lead approval)"
LEAD_ID=$(gh api "users/$LEAD" --jq .id)
if gh api -X PUT "repos/$REPO/environments/production" --input - >/dev/null 2>&1 <<JSON
{ "reviewers": [ { "type": "User", "id": $LEAD_ID } ],
  "deployment_branch_policy": { "protected_branches": true, "custom_branch_policies": false } }
JSON
then echo "  production environment requires approval by $LEAD"
else echo "  (skipped: environment reviewers not available on this plan; keep deploy credentials lead-only instead)"
fi

echo "== verify"
gh api "repos/$REPO/rules/branches/main" --jq '.[].type' | sed 's/^/  active rule: /'
gh api "repos/$REPO/collaborators" --jq '.[] | "  collaborator: \(.login) (\(.role_name))"'
