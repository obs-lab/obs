#!/usr/bin/env bash
set -euo pipefail

COMMIT_MSG="Initial public release"

PRIVATE_PATTERN='(^|/)\.env($|\.)|(^|/)data/|\.db$|\.sqlite[23]?$|(^|/)images/|auth\.db|access_log|chat_history|\.faiss$|\.index$|session_signing\.key|(^|/)\.key$|(^|/)config\.json$|obs_private_key\.txt|obs_public_key\.txt|licenze_registro\.json|(^|/)licenze_emesse/|(^|/)licenses_issued/|\.obslic$|obs_license_core\.py|obs_keygen\.py|obs_licensegen(_web)?\.py|test_license\.py'

cd "$(git rev-parse --show-toplevel)"
REPO_DIR="$(pwd)"
echo "--- Working directory: $REPO_DIR ---"

echo "--- Current remotes (will NOT be changed) ---"
git remote -v

BACKUP_DIR="../$(basename "$REPO_DIR")_backup_$(date +%Y%m%d_%H%M%S)"
echo "--- Creating a full backup in: $BACKUP_DIR ---"
cp -R "$REPO_DIR" "$BACKUP_DIR"
echo "Backup created. If something goes wrong, restore from there."

touch .gitignore
grep -qxF "OBS_HANDOFF.md" .gitignore || echo "OBS_HANDOFF.md" >> .gitignore

echo "--- Checking for already-tracked private files ---"
TRACKED_PRIVATE="$(git ls-files | grep -Ei "$PRIVATE_PATTERN" \
  | grep -viE '(^|/)env\.example$' || true)"
if [ -n "$TRACKED_PRIVATE" ]; then
  echo "STOP: these private files are TRACKED by git."
  echo "$TRACKED_PRIVATE"
  echo
  echo "Remove them from tracking before proceeding, for example:"
  echo "  git rm --cached <file>    (keeps the file on disk, removes it from git)"
  echo "then add them to .gitignore and run this again."
  echo "Backup saved at $BACKUP_DIR"
  exit 1
fi

echo "--- Creating a clean history (single commit) ---"
git checkout -q --orphan storia_pulita_tmp
git add -A

STAGED_PRIVATE="$(git diff --cached --name-only | grep -Ei "$PRIVATE_PATTERN" \
  | grep -viE '(^|/)env\.example$' || true)"
if [ -n "$STAGED_PRIVATE" ]; then
  echo "STOP: private files are staged, aborting."
  echo "$STAGED_PRIVATE"
  echo
  echo "Add them to .gitignore, then run this again."
  echo "To go back to how it was:  git checkout -q main && git branch -D storia_pulita_tmp"
  echo "Backup saved at $BACKUP_DIR"
  exit 1
fi

echo
echo "=== FILES THAT WILL BE PUBLISHED ==="
git status --short
echo "===================================="
echo
echo "About to:"
echo "  1) replace all history with ONE commit: \"$COMMIT_MSG\""
echo "  2) FORCE-push to YOUR two repos (the same remotes shown above)."
echo
echo "The repos remain yours: same address, same token, same settings."
echo "Only the commit history changes."
echo
read -r -p "Confirm? (type: PUBLISH) " ANS
if [ "$ANS" != "PUBLISH" ]; then
  echo "Cancelled before pushing. Nothing was sent online."
  echo "To go back to exactly how it was:"
  echo "  git checkout -q main && git branch -D storia_pulita_tmp"
  echo "Backup saved at $BACKUP_DIR"
  exit 1
fi

git commit -q -m "$COMMIT_MSG"
git branch -D main 2>/dev/null || true
git branch -m main

echo "--- Publishing to origin (force) ---"
git push -f origin main

echo "--- Publishing to obs (force) ---"
git push -f obs main

echo
echo "--- Done. History cleaned on both of your repos. ---"
echo "Backup of the old history kept at: $BACKUP_DIR"
echo
echo "REMINDER: if the old commits contained real secrets"
echo "(.env, passwords, tokens, keys), they still need to be REGENERATED:"
echo "removing them from history does not make them secure again."