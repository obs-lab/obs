import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

VS_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/vectorstore")
INDEX_FILE = VS_DIR / "chunks.json"

PLAN = {
    "obs_energia_1":   0,
    "obs_energia_2":   2,
    "obs_logistica_1": 3,
    "obs_logistica_2": 5,
    "obs_energia_3":   8,
    "obs_logistica_3": 9,
    "obs_energia_4":   13,
    "obs_logistica_4": 14,
    "obs_incrocio_1":  20,
    "obs_incrocio_2":  27,
}


def main():
    if not INDEX_FILE.exists():
        print("Non trovo " + str(INDEX_FILE))
        print("Passa come argomento la cartella del vectorstore.")
        return

    chunks = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    backup = INDEX_FILE.with_suffix(".json.bak")
    if not backup.exists():
        backup.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    base = datetime.utcnow() - timedelta(days=30)

    touched = {}
    for c in chunks:
        name = Path(c.get("filename", "")).stem
        if name not in PLAN:
            continue
        ts = base + timedelta(days=PLAN[name], hours=9)
        c["timestamp"] = ts.isoformat()
        touched[name] = ts.date().isoformat()

    if not touched:
        print("Nessun documento del piano trovato nell'indice.")
        print("Nomi attesi: " + ", ".join(sorted(PLAN)))
        return

    backup = INDEX_FILE.with_suffix(".json.bak")
    INDEX_FILE.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Backup salvato in " + str(backup))
    for name in sorted(touched, key=lambda n: PLAN[n]):
        print("  " + name.ljust(18) + touched[name])
    print("Riavvia OBS per ricaricare l'indice.")


if __name__ == "__main__":
    main()
