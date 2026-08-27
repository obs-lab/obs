#!/usr/bin/env bash
set -uo pipefail

SORGENTE=""
FORCE=0
DRYRUN=0

usage() {
  echo "Uso: ./obs_restore.sh ARCHIVIO [--dry-run] [--force]"
  echo ""
  echo "  ARCHIVIO puo' essere un file obs_data_*.tar.gz oppure la cartella"
  echo "  obs_data_* prodotta da obs_backup.sh."
  echo ""
  echo "  --dry-run   verifica il backup e mostra cosa farebbe, senza scrivere"
  echo "  --force     ripristina anche se le verifiche falliscono (sconsigliato)"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRYRUN=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) SORGENTE="$1"; shift ;;
  esac
done

if [ -z "$SORGENTE" ]; then
  usage
  exit 1
fi
if [ ! -e "$SORGENTE" ]; then
  echo "STOP: non trovo $SORGENTE"
  exit 1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  ROOT="$(git rev-parse --show-toplevel)"
fi
cd "$ROOT"
DATA_DIR="${OBS_DATA_DIR:-$ROOT/data}"

echo ""
echo "OBS-LAB - ripristino dell'archivio"
echo "  sorgente:     $SORGENTE"
echo "  destinazione: $DATA_DIR"
echo ""

PORT="${OBS_PORT:-8000}"
if command -v lsof >/dev/null 2>&1 && lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "STOP: qualcosa e' in ascolto sulla porta $PORT. Ferma OBS prima di ripristinare."
  exit 1
fi

TMP=""
if [ -d "$SORGENTE" ]; then
  WORK="$(cd "$SORGENTE" && pwd)"
else
  TMP="$(mktemp -d)"
  echo "--- Estrazione ---"
  tar xzf "$SORGENTE" -C "$TMP" || { echo "STOP: archivio non estraibile."; rm -rf "$TMP"; exit 1; }
  WORK="$(ls -1d "$TMP"/obs_data_* 2>/dev/null | head -1)"
  [ -z "$WORK" ] && WORK="$TMP"
  echo "  estratto"
fi

if [ ! -d "$WORK/data" ]; then
  echo "STOP: nel backup non trovo la cartella data."
  [ -n "$TMP" ] && rm -rf "$TMP"
  exit 1
fi

PY=""
for cand in "$ROOT/venv/bin/python" "$ROOT/venv/bin/python3" \
            "$ROOT/backend/venv/bin/python" "${VIRTUAL_ENV:-}/bin/python"; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  command -v python3 >/dev/null 2>&1 && PY="python3"
  [ -z "$PY" ] && command -v python >/dev/null 2>&1 && PY="python"
fi
if [ -n "$PY" ] && ! "$PY" -c "import faiss" >/dev/null 2>&1; then
  echo "  nota: l'interprete $PY non vede faiss, il controllo sull'indice sara' parziale"
fi

pulizia() {
  [ -n "$TMP" ] && rm -rf "$TMP"
}

echo "--- Verifica 1: somme di controllo ---"
if [ -f "$WORK/CHECKSUMS.txt" ]; then
  SUMTOOL=""
  command -v shasum >/dev/null 2>&1 && SUMTOOL="shasum -a 256 -c --quiet"
  [ -z "$SUMTOOL" ] && command -v sha256sum >/dev/null 2>&1 && SUMTOOL="sha256sum -c --quiet"
  if [ -n "$SUMTOOL" ]; then
    if (cd "$WORK/data" && $SUMTOOL "$WORK/CHECKSUMS.txt" >/dev/null 2>&1); then
      echo "  tutte le somme corrispondono"
      SOMME=0
    else
      echo "  ALCUNI FILE NON CORRISPONDONO"
      SOMME=1
    fi
  else
    echo "  saltata, nessuno strumento di hash disponibile"
    SOMME=0
  fi
else
  echo "  saltata, il backup non contiene CHECKSUMS.txt"
  SOMME=0
fi

echo "--- Verifica 2: file svuotati ---"
if [ "$(uname -s)" = "Darwin" ]; then
  STAT_BLOCKS="stat -f %b"
else
  STAT_BLOCKS="stat -c %b"
fi
export STAT_BLOCKS
VUOTI="$(find "$WORK/data" -type f -size +0c -exec sh -c '
  b=$($STAT_BLOCKS "$1" 2>/dev/null)
  case "$b" in "" ) exit 0 ;; esac
  [ "$b" -eq 0 ] 2>/dev/null && echo "$1"
' _ {} \; 2>/dev/null | head -20)"
if [ -n "$VUOTI" ]; then
  echo "  TROVATI FILE CON METADATI MA SENZA CONTENUTO:"
  echo "$VUOTI" | sed 's/^/    /'
  SVUOTATI=1
else
  echo "  nessuno"
  SVUOTATI=0
fi

echo "--- Verifica 3: coerenza fra indice e registro ---"
COERENZA="$("$PY" - "$WORK/data" <<'EOF' 2>/dev/null
import json, sys
from pathlib import Path
vs = Path(sys.argv[1]) / "vector_store"
try:
    n = len(json.load(open(vs / "chunks.json")))
except Exception as e:
    print("ERRORE chunks.json non leggibile"); raise SystemExit(0)
try:
    import faiss
    v = faiss.read_index(str(vs / "faiss.index")).ntotal
except Exception:
    print("PARZIALE chunk=%d indice non verificabile" % n); raise SystemExit(0)
print(("OK " if n == v else "DISALLINEATO ") + "chunk=%d vettori=%d" % (n, v))
EOF
)"
[ -z "$COERENZA" ] && COERENZA="NON VERIFICATO"
echo "  $COERENZA"

if [ -f "$WORK/MANIFESTO.csv" ]; then
  echo "--- Contenuto del backup ---"
  echo "  documenti: $(( $(wc -l < "$WORK/MANIFESTO.csv") - 1 ))"
  echo "  aziende:   $(tail -n +2 "$WORK/MANIFESTO.csv" | cut -d, -f3 | sort -u | tr '\n' ' ')"
fi

PROBLEMI=0
[ "$SOMME" -eq 1 ] && PROBLEMI=1
[ "$SVUOTATI" -eq 1 ] && PROBLEMI=1
case "$COERENZA" in ERRORE*|DISALLINEATO*) PROBLEMI=1 ;; esac

echo ""
if [ "$PROBLEMI" -eq 1 ] && [ "$FORCE" -eq 0 ]; then
  echo "STOP: il backup non ha superato le verifiche. Nulla e' stato scritto."
  echo "  Prova un backup piu' vecchio, oppure rilancia con --force se sai"
  echo "  cosa stai facendo."
  pulizia
  exit 1
fi

if [ "$DRYRUN" -eq 1 ]; then
  echo "Prova a vuoto. Il backup e' utilizzabile. Nulla e' stato scritto."
  pulizia
  exit 0
fi

echo "Sto per SOSTITUIRE $DATA_DIR con il contenuto del backup."
echo "L'archivio attuale verra' spostato di lato, non cancellato."
printf "Confermi? (scrivi RIPRISTINA) "
read -r ANS
if [ "$ANS" != "RIPRISTINA" ]; then
  echo "Annullato. Nulla e' stato scritto."
  pulizia
  exit 1
fi

if [ -d "$DATA_DIR" ]; then
  LATO="${DATA_DIR}_sostituito_$(date +%Y%m%d_%H%M%S)"
  mv "$DATA_DIR" "$LATO"
  echo "--- Archivio precedente spostato in $LATO ---"
fi

mkdir -p "$DATA_DIR"
if command -v rsync >/dev/null 2>&1; then
  rsync -a "$WORK/data/" "$DATA_DIR/"
else
  (cd "$WORK/data" && tar cf - .) | (cd "$DATA_DIR" && tar xf -)
fi

echo "--- Ripristinati $(find "$DATA_DIR" -type f | wc -l | tr -d ' ') file ---"
pulizia
echo ""
echo "Fatto. Riavvia OBS e verifica che i documenti siano al loro posto."
echo "Se qualcosa non torna, l'archivio precedente e' ancora in ${LATO:-nessuna copia}."
echo ""
