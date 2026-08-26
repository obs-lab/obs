#!/usr/bin/env bash
set -euo pipefail

NOTE="$*"

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

if [ -z "$NOTE" ] && [ -t 0 ]; then
  printf "Cosa hai aggiornato (invio per saltare): "
  read -r NOTE
fi

NOTE="$(printf '%s' "$NOTE" | tr '\n\r\t' '   ' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"

SUBJECT="update $(date +%d/%m/%Y)"
ONE_LINE="${SUBJECT} - ${NOTE}"

echo "--- Messaggio del commit: ---"
if [ -z "$NOTE" ]; then
  echo "$SUBJECT"
  git commit -m "$SUBJECT"
elif [ "${#ONE_LINE}" -le 72 ]; then
  echo "$ONE_LINE"
  git commit -m "$ONE_LINE"
else
  echo "$SUBJECT"
  echo "$NOTE"
  git commit -m "$SUBJECT" -m "$NOTE"
fi

git push
git push obs main
echo "--- Commit terminato. ---"
