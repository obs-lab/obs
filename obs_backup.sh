#!/usr/bin/env bash
set -uo pipefail

KEEP="${OBS_BACKUP_KEEP:-7}"
DEST_ROOT="${OBS_BACKUP_DIR:-}"
FORCE=0
COMPRESS=1

usage() {
  echo "Uso: ./obs_backup.sh [--dest CARTELLA] [--keep N] [--no-compress] [--force]"
  echo ""
  echo "  Crea una copia verificata dell'archivio OBS (la cartella data)."
  echo "  Il codice non viene salvato: quello sta su git."
  echo ""
  echo "  --dest CARTELLA  dove scrivere i backup. Difetto: ../obs-backup"
  echo "  --keep N         quanti backup conservare. Difetto: 7"
  echo "  --no-compress    lascia la copia come cartella invece di un archivio"
  echo "  --force          procede anche se OBS risulta in esecuzione (sconsigliato)"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST_ROOT="${2:-}"; shift 2 ;;
    --keep) KEEP="${2:-7}"; shift 2 ;;
    --no-compress) COMPRESS=0; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Argomento non riconosciuto: $1"; usage; exit 1 ;;
  esac
done

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  ROOT="$(git rev-parse --show-toplevel)"
fi
cd "$ROOT"

DATA_DIR="${OBS_DATA_DIR:-$ROOT/data}"
if [ ! -d "$DATA_DIR" ]; then
  echo "STOP: cartella dati non trovata in $DATA_DIR"
  exit 1
fi

[ -z "$DEST_ROOT" ] && DEST_ROOT="$ROOT/../obs-backup"
mkdir -p "$DEST_ROOT" || { echo "STOP: non riesco a creare $DEST_ROOT"; exit 1; }
DEST_ROOT="$(cd "$DEST_ROOT" && pwd)"

echo ""
echo "OBS-LAB - backup dell'archivio"
echo "  origine:      $DATA_DIR"
echo "  destinazione: $DEST_ROOT"
echo ""

PORT="${OBS_PORT:-8000}"
if [ "$FORCE" -eq 0 ]; then
  if command -v lsof >/dev/null 2>&1 && lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "STOP: qualcosa e' in ascolto sulla porta $PORT."
    echo "  Ferma OBS prima di fare il backup: una copia presa mentre il server"
    echo "  scrive puo' contenere un indice e un registro disallineati."
    echo "  Se sei certo che OBS sia fermo, rilancia con --force."
    exit 1
  fi
fi

echo "--- Verifica di coerenza prima della copia ---"
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
COERENZA="$("$PY" - "$DATA_DIR" <<'EOF' 2>/dev/null
import json, sys
from pathlib import Path
vs = Path(sys.argv[1]) / "vector_store"
try:
    n = len(json.load(open(vs / "chunks.json")))
except Exception as e:
    print("ERRORE chunks.json non leggibile: " + str(e)[:80]); raise SystemExit(0)
try:
    import faiss
    idx = faiss.read_index(str(vs / "faiss.index"))
    v = idx.ntotal
except Exception as e:
    print("PARZIALE chunk=%d indice non verificabile: %s" % (n, str(e)[:60])); raise SystemExit(0)
print(("OK " if n == v else "DISALLINEATO ") + "chunk=%d vettori=%d" % (n, v))
EOF
)"
[ -z "$COERENZA" ] && COERENZA="NON VERIFICATO ambiente python non disponibile"
echo "  $COERENZA"

case "$COERENZA" in
  ERRORE*|DISALLINEATO*)
    if [ "$FORCE" -eq 0 ]; then
      echo ""
      echo "STOP: l'archivio di partenza non e' coerente."
      echo "  Fare il backup adesso significa conservare una fotografia gia' rotta."
      echo "  Se vuoi comunque una copia di sicurezza, rilancia con --force."
      exit 1
    fi
    echo "  proseguo su richiesta esplicita (--force)"
    ;;
esac
echo ""

STAMP="$(date +%Y%m%d_%H%M%S)"
WORK="$DEST_ROOT/obs_data_$STAMP"

echo "--- Copia ---"
mkdir -p "$WORK"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude 'upload_tmp/' --exclude 'models/' "$DATA_DIR/" "$WORK/data/"
else
  mkdir -p "$WORK/data"
  (cd "$DATA_DIR" && tar cf - --exclude upload_tmp --exclude models .) | (cd "$WORK/data" && tar xf -)
fi
echo "  copiati $(find "$WORK/data" -type f | wc -l | tr -d ' ') file"

echo "--- Somme di controllo ---"
SUMTOOL=""
command -v shasum >/dev/null 2>&1 && SUMTOOL="shasum -a 256"
[ -z "$SUMTOOL" ] && command -v sha256sum >/dev/null 2>&1 && SUMTOOL="sha256sum"
if [ -n "$SUMTOOL" ]; then
  (cd "$WORK/data" && find . -type f -print0 | xargs -0 $SUMTOOL) > "$WORK/CHECKSUMS.txt" 2>/dev/null
  echo "  scritte $(wc -l < "$WORK/CHECKSUMS.txt" | tr -d ' ') somme"
else
  echo "  ATTENZIONE: nessuno strumento di hash trovato, verifica non disponibile"
fi

echo "--- Manifesto ---"
"$PY" - "$WORK" "$COERENZA" <<'EOF' 2>/dev/null
import csv, json, sys
from pathlib import Path
work = Path(sys.argv[1]); coerenza = sys.argv[2]
data = work / "data"
righe = []
try:
    chunks = json.load(open(data / "vector_store" / "chunks.json"))
    visti = {}
    for c in chunks:
        d = c.get("doc_id", "")
        if d not in visti:
            visti[d] = {
                "doc_id": d,
                "titolo": c.get("titolo", ""),
                "azienda": c.get("azienda", ""),
                "folder_id": c.get("folder_id", ""),
                "owner_id": c.get("owner_id", ""),
                "tipo": c.get("tipo", ""),
                "timestamp": c.get("timestamp", ""),
                "chunk": 0,
            }
        visti[d]["chunk"] += 1
    righe = list(visti.values())
except Exception as e:
    print("  manifesto non generato: " + str(e)[:70])

if righe:
    campi = list(righe[0].keys())
    with open(work / "MANIFESTO.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campi)
        w.writeheader()
        w.writerows(righe)
    print("  %d documenti, %d chunk" % (len(righe), sum(r["chunk"] for r in righe)))

info = {
    "creato": sys.argv[1].split("obs_data_")[-1],
    "coerenza": coerenza,
    "documenti": len(righe),
    "chunk": sum(r["chunk"] for r in righe) if righe else 0,
    "versione_obs": "2.6.0",
}
(work / "INFO.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
EOF

if [ "$COMPRESS" -eq 1 ]; then
  echo "--- Compressione ---"
  (cd "$DEST_ROOT" && tar czf "obs_data_$STAMP.tar.gz" "obs_data_$STAMP") && rm -rf "$WORK"
  FINALE="$DEST_ROOT/obs_data_$STAMP.tar.gz"
else
  FINALE="$WORK"
fi
echo "  $FINALE"
echo "  $(du -sh "$FINALE" | cut -f1)"

echo "--- Rotazione (conservo gli ultimi $KEEP) ---"
COUNT=0
for vecchio in $(ls -1dt "$DEST_ROOT"/obs_data_* 2>/dev/null); do
  COUNT=$((COUNT + 1))
  if [ "$COUNT" -gt "$KEEP" ]; then
    rm -rf "$vecchio"
    echo "  rimosso $(basename "$vecchio")"
  fi
done
echo "  presenti $(ls -1d "$DEST_ROOT"/obs_data_* 2>/dev/null | wc -l | tr -d ' ') backup"

echo ""
echo "--- Backup completato. ---"
echo "Per ripristinarlo:  ./obs_restore.sh $FINALE"
echo ""
