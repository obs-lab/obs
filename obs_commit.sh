#!/usr/bin/env bash
set -euo pipefail

FIX_NUMBER="${1:-1}"

PRIVATE_PATTERN='(^|/)\.env($|\.)|(^|/)data/|\.db$|\.sqlite[23]?$|(^|/)images/|auth\.db|access_log|chat_history|\.faiss$|\.index$|session_signing\.key|(^|/)\.key$'

cd "$(git rev-parse --show-toplevel)"

grep -qxF "OBS_HANDOFF.md" .gitignore || echo "OBS_HANDOFF.md" >> .gitignore

echo "--- Controllo file privati gia' tracciati ---"
TRACKED_PRIVATE="$(git ls-files | grep -Ei "$PRIVATE_PATTERN" | grep -viE '(^|/)env\.example$' || true)"
if [ -n "$TRACKED_PRIVATE" ]; then
  echo "STOP: questi file privati risultano TRACCIATI da git e NON verranno committati."
  echo "$TRACKED_PRIVATE"
  echo
  echo "Rimuovili dal tracking prima di procedere, ad esempio:"
  echo "  git rm --cached <file>    (mantiene il file su disco, lo toglie da git)"
  exit 1
fi

git add -A

echo "--- Controllo file privati nello stage ---"
STAGED_PRIVATE="$(git diff --cached --name-only | grep -Ei "$PRIVATE_PATTERN" | grep -viE '(^|/)env\.example$' || true)"
if [ -n "$STAGED_PRIVATE" ]; then
  echo "STOP: file privati nello stage, commit annullato."
  echo "$STAGED_PRIVATE"
  git reset >/dev/null
  exit 1
fi

echo "--- File che verranno committati: ---"
git status --short

if git diff --cached --quiet; then
  echo "Niente da committare."
  exit 0
fi

git commit -m "obs $(date +%d/%m/%Y) fix #${FIX_NUMBER}"
git push
git push obs main
echo "--- Commit terminato. ---"
