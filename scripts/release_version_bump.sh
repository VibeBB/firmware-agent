#!/usr/bin/env bash
# Release version-bump state machine for firmware-agent: resolve the target
# version, commit the bumped files (a direct push to main, or a gated pull
# request when the push rule rejects it), and report the released sha.
#
# Inputs arrive as environment variables: BUMP, SET_VERSION, DRY_RUN,
# GH_TOKEN, GITHUB_*; poll/retry counts are RELEASE_BUMP_* knobs so the
# script can be rehearsed quickly in tests.
set -euo pipefail

RETRY_ATTEMPTS=${RELEASE_BUMP_RETRY_ATTEMPTS:-5}
RETRY_DELAY_SECONDS=${RELEASE_BUMP_RETRY_DELAY_SECONDS:-10}
GATED_POLL_ATTEMPTS=${RELEASE_BUMP_GATED_POLL_ATTEMPTS:-10}
GATED_POLL_SECONDS=${RELEASE_BUMP_GATED_POLL_SECONDS:-30}
GATED_APPROVE_SECONDS=${RELEASE_BUMP_GATED_APPROVE_SECONDS:-10}
RUN_DISCOVER_ATTEMPTS=${RELEASE_BUMP_RUN_DISCOVER_ATTEMPTS:-30}
RUN_DISCOVER_SECONDS=${RELEASE_BUMP_RUN_DISCOVER_SECONDS:-10}
RUN_CONCLUSION_ATTEMPTS=${RELEASE_BUMP_RUN_CONCLUSION_ATTEMPTS:-6}
RUN_CONCLUSION_SECONDS=${RELEASE_BUMP_RUN_CONCLUSION_SECONDS:-10}
MERGE_WAIT_ATTEMPTS=${RELEASE_BUMP_MERGE_WAIT_ATTEMPTS:-40}
MERGE_WAIT_SECONDS=${RELEASE_BUMP_MERGE_WAIT_SECONDS:-30}
GATE_WORKFLOWS=${RELEASE_BUMP_GATE_WORKFLOWS:-"ci.yml workflow-lint.yml"}

BUMP=${BUMP:-patch}
SET_VERSION=${SET_VERSION:-}
DRY_RUN=${DRY_RUN:-false}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "${GITHUB_WORKSPACE:-$PWD}"

retry() {
  # Transient GitHub API/server errors (HTTP 5xx, TLS resets, truncated
  # responses) should not hard-fail the release: retry gh/git calls with
  # backoff before giving up.
  local attempt
  for ((attempt = 1; attempt <= RETRY_ATTEMPTS; attempt++)); do
    if "$@"; then
      return 0
    fi
    if [ "$attempt" -lt "$RETRY_ATTEMPTS" ]; then
      sleep $((attempt * RETRY_DELAY_SECONDS))
    fi
  done
  return 1
}

write_output() {
  printf '%s\n' "$1" >> "$GITHUB_OUTPUT"
}

write_summary() {
  printf '%s\n' "$1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '%s\n' "$1" >> "$GITHUB_STEP_SUMMARY"
  fi
}

# Pull_request runs on the bot branch queue as approval-gated
# action_required runs; poll and approve. A rejected approval is
# non-fatal: the dispatched run below still satisfies required checks.
approve_gated_runs() {
  local branch=$1
  local gated_seen=0 empty_streak=0 attempt batch gated
  for ((attempt = 1; attempt <= GATED_POLL_ATTEMPTS; attempt++)); do
    batch=$(retry gh run list --repo "$GITHUB_REPOSITORY" --branch "$branch" \
      --event pull_request --status action_required --json databaseId \
      --jq '.[].databaseId' || true)
    if [ -z "$batch" ]; then
      empty_streak=$((empty_streak + 1))
      if { [ "$gated_seen" -eq 0 ] && [ "$empty_streak" -ge 3 ]; } ||
         { [ "$gated_seen" -eq 1 ] && [ "$empty_streak" -ge 2 ]; }; then
        break
      fi
      sleep "$GATED_POLL_SECONDS"
      continue
    fi
    empty_streak=0
    gated_seen=1
    for gated in $batch; do
      retry gh api -X POST "repos/$GITHUB_REPOSITORY/actions/runs/$gated/approve" || true
    done
    sleep "$GATED_APPROVE_SECONDS"
  done
}

# Dispatch the gate workflows on the bump branch, then watch each run to a
# conclusion. A missing run or a non-success conclusion fails the release
# and leaves the PR open for manual review.
gate_bump_pr() {
  local branch=$1
  local workflow run_id attempt conclusion failed started
  local -a workflows=()
  read -r -a workflows <<< "$GATE_WORKFLOWS"
  started=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  for workflow in "${workflows[@]}"; do
    retry gh workflow run "$workflow" --repo "$GITHUB_REPOSITORY" --ref "$branch"
  done
  failed=0
  for workflow in "${workflows[@]}"; do
    run_id=""
    for ((attempt = 1; attempt <= RUN_DISCOVER_ATTEMPTS; attempt++)); do
      sleep "$RUN_DISCOVER_SECONDS"
      run_id=$(retry gh run list --repo "$GITHUB_REPOSITORY" --workflow "$workflow" \
        --branch "$branch" --event workflow_dispatch --created ">=$started" \
        --json databaseId --jq '.[0].databaseId // empty' || true)
      [ -n "$run_id" ] && break
    done
    if [ -z "$run_id" ]; then
      write_summary "$workflow workflow_dispatch for $branch was not observed; the version-bump PR was left open"
      exit 1
    fi
    echo "$workflow run for $branch: ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${run_id}"
    gh run watch --repo "$GITHUB_REPOSITORY" "$run_id" --interval 30 || true
    # An empty conclusion is a transient API failure, not a run verdict:
    # re-query until the API reports the conclusion.
    conclusion=""
    for ((attempt = 1; attempt <= RUN_CONCLUSION_ATTEMPTS; attempt++)); do
      conclusion=$(retry gh run view --repo "$GITHUB_REPOSITORY" "$run_id" \
        --json conclusion --jq '.conclusion // empty' || true)
      [ -n "$conclusion" ] && break
      sleep "$RUN_CONCLUSION_SECONDS"
    done
    conclusion="${conclusion:-unknown}"
    echo "$workflow conclusion for $branch: $conclusion"
    if [ "$conclusion" != "success" ]; then
      failed=1
    fi
  done
  if [ "$failed" -ne 0 ]; then
    write_summary "version-bump PR checks failed; the PR was left open for manual review"
    exit 1
  fi
}

# No bypass actor is configured, so the pull_request rule can reject a
# direct push. Route the bump commit through a pull request instead:
# approve the gated pull_request runs, dispatch the gate workflows on the
# branch, then arm auto-merge and wait for the merge to land on main.
bump_via_pull_request() {
  local branch=$1
  local body pr_url attempt merged merged_at
  retry git push origin "HEAD:refs/heads/${branch}"
  body=$(printf '%s\n' \
    "Automated version bump for the Release workflow." \
    "" \
    "version: v${VERSION}" \
    "workflow run: ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}")
  pr_url=$(retry gh pr create \
    --repo "$GITHUB_REPOSITORY" \
    --base main \
    --head "$branch" \
    --title "Release v${VERSION}: update version files" \
    --body "$body")
  write_summary "version-bump PR: $pr_url"
  approve_gated_runs "$branch"
  gate_bump_pr "$branch"
  # Arm auto-merge on the version-bump PR. Checks are already green here
  # so the merge lands immediately; arming failure leaves the PR open for
  # manual merge.
  if ! retry gh pr merge --repo "$GITHUB_REPOSITORY" --auto --squash --delete-branch "$pr_url"; then
    write_summary "version-bump PR auto-merge could not be armed; the PR was left open for manual review"
    echo "::error::version-bump PR $pr_url was not auto-merged; merge it, then re-run Release with version=${VERSION}." >&2
    exit 1
  fi
  # Wait for the merge to land on main so the release SHA is the real main
  # tip, not the branch head.
  merged=false
  for ((attempt = 1; attempt <= MERGE_WAIT_ATTEMPTS; attempt++)); do
    merged_at=$(retry gh api "repos/$GITHUB_REPOSITORY/pulls/${pr_url##*/}" \
      --jq '.merged_at // empty' || true)
    [ -n "$merged_at" ] && { merged=true; break; }
    sleep "$MERGE_WAIT_SECONDS"
  done
  if [ "$merged" != true ]; then
    write_summary "version-bump PR did not merge within the wait; it was left open"
    echo "::error::merge $pr_url, then re-run Release with version=${VERSION}." >&2
    exit 1
  fi
  git fetch -q origin main
  write_output "sha=$(git rev-parse origin/main)"
}

SET_VERSION="${SET_VERSION#v}"
CURRENT=$(python3 -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
SKIP_COMMIT=false
# A dry run must not write main: take the no-commit path at the current
# version so verify/install-smoke/zip all still exercise.
if [ "$DRY_RUN" = "true" ]; then
  VERSION="$CURRENT"
  python3 "$SCRIPT_DIR/bump_version.py" --root "$PWD" --dry-run --bump "$BUMP" >/dev/null
  SKIP_COMMIT=true
elif [ -n "$SET_VERSION" ]; then
  if [ "$SET_VERSION" = "$CURRENT" ]; then
    VERSION="$CURRENT"
    python3 "$SCRIPT_DIR/bump_version.py" --root "$PWD" --dry-run --bump patch >/dev/null
    SKIP_COMMIT=true
  else
    VERSION=$(python3 "$SCRIPT_DIR/bump_version.py" --root "$PWD" --set "$SET_VERSION")
  fi
else
  VERSION=$(python3 "$SCRIPT_DIR/bump_version.py" --root "$PWD" --bump "$BUMP")
fi
# A dry run replays the current version, whose tag already exists; only
# real releases fail on a duplicate tag.
if [ "$DRY_RUN" != "true" ] && git ls-remote --exit-code --tags origin "refs/tags/v${VERSION}"; then
  echo "::error::tag v${VERSION} already exists" >&2
  exit 1
fi
if [ "$SKIP_COMMIT" = true ]; then
  write_output "sha=$(git rev-parse HEAD)"
else
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git add plugins/firmware/.plugin/plugin.json pyproject.toml src/firmware/__init__.py \
    CHANGELOG.md plugins/firmware/skills/*/SKILL.md uv.lock
  git commit -m "Release v${VERSION}: update version files"
  if retry git push origin HEAD:main; then
    write_output "sha=$(git rev-parse HEAD)"
  else
    echo "::warning::direct push to main rejected; routing the version bump through a pull request"
    bump_via_pull_request "bot/release-bump-v${VERSION}-${GITHUB_RUN_ID}"
  fi
fi
write_output "version=${VERSION}"
write_output "tag=v${VERSION}"
