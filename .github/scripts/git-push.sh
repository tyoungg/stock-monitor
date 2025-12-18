#!/usr/bin/env bash
set -euo pipefail

# Simple helper to commit and push changes from the repo root.
# Usage:
#   .github/scripts/git-push.sh "Commit message here"
# If no message is supplied, a sensible default will be used.

cd "$(dirname "$0")/../.." || exit 1

echo "Repository root: $(pwd)"

git status --porcelain | sed -n '1,200p'
if [ -z "$(git status --porcelain)" ]; then
  echo "No changes to commit. Exiting."
  exit 0
fi

MSG="${1:-chore: add CI, Discord embeds, artifacts, and improve monitor}"

echo "Staging all changes..."
git add -A

echo "Committing with message: $MSG"
git commit -m "$MSG"

BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Push, set upstream if needed
if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
  echo "Pushing branch $BRANCH to origin..."
  git push origin "$BRANCH"
else
  echo "Branch $BRANCH has no upstream; pushing and setting upstream..."
  git push --set-upstream origin "$BRANCH"
fi

echo "Push complete. Last commit:" 
git --no-pager log -1 --pretty=format:'%h %s (%an, %cr)'

echo "Tip: Visit https://github.com/$(git config --get remote.origin.url | sed -E 's#.*[:/]([^/]+/[^/.]+)(\.git)?#\1#')/actions to view workflow runs."